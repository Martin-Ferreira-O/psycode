"""Pruebas sintéticas: toda la red se sustituye por httpx.MockTransport."""
from dataclasses import replace
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
import json
from pathlib import Path
import socket
import tempfile
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase
import httpx

from backend.apps.alerts.repositories import AlertsRepository
from backend.apps.alerts.services import AlertsService
from backend.apps.alerts.tests.test_persistence import FakeDatabase
from backend.apps.analysis.audit import AnalysisAudit
from backend.apps.analysis.clients import JevAnalizador, SpeechmaticsTranscriptor
from backend.apps.analysis.domain import AnalysisResult, AnalysisState, Fragment, FragmentRejected
from backend.apps.analysis.errors import JevContextLimit
from backend.apps.analysis.ledger import FileFragmentLedger
from backend.apps.analysis.providers.http import ProviderError, SubmissionUncertain, request
from backend.apps.analysis.providers.jev_contract import CONTEXT_CHOICES, validate_response
from backend.apps.analysis.providers.settings import Settings
from backend.apps.analysis.services import AnalysisService
from backend.config.composition import analysis_worker


def answer(level=None, context="afirmacion_propia", model="jev-1.14.0"):
    answers = {"context": {"type": "choice", "choice": context, "confidence": 1.,
                           "probabilities": {k: float(k == context) for k in CONTEXT_CHOICES}}}
    answers.update({f"signal_{i}": {"type": "noul", "noul": .9 if i == level else .1}
                    for i in range(8)})
    return {"model": model, "answers": answers, "usage": {"input_tokens": 30, "output_tokens": 15}}


class IntegrationTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.audio = self.root / "fragment.pcm"
        self.audio.write_bytes(b"\0\0" * 64000)
        self.fragment = Fragment(str(uuid4()), 0, "box-1", datetime.now(timezone.utc),
                                 self.audio, end=64000)
        self.settings = Settings(speechmatics_key="fake-speech-key", jev_key="fake-jev-key",
                                 external_enabled=True)
        self.db = FakeDatabase()
        self.store = AlertsRepository(self.db)
        self.store.ensure_schema()
        self.audit = AnalysisAudit(lambda: self.db["audit_events"])
        self.requests, self.jev_requests = [], []
        self.text = "Ojalá no despertar"
        self.jev_answer = answer(1)
        self.delete_status = 200
        self.post_status = 201
        self.jev_status = 200
        self.invalid_transcript = False
        self.transcript_results = None
        self.network_block = patch.object(socket.socket, "connect", side_effect=AssertionError("Red prohibida"))
        self.network_block.start()
        self.addCleanup(self.network_block.stop)

    def speech_http(self, req):
        self.requests.append(req)
        if req.method == "POST":
            return httpx.Response(self.post_status, json={"id": "job-1"})
        if req.method == "DELETE":
            return httpx.Response(self.delete_status)
        if req.url.path.endswith("/transcript"):
            if self.invalid_transcript:
                return httpx.Response(200, json={"results": [{"type": "word", "alternatives": []}]})
            if self.transcript_results is not None:
                return httpx.Response(200, json={"results": self.transcript_results})
            return httpx.Response(200, json={"results": [
                {"type": "word", "start_time": 0, "end_time": 1,
                 "alternatives": [{"content": self.text, "speaker": "S1"}]}]})
        return httpx.Response(200, json={"job": {"status": "done"}})

    def jev_http(self, req):
        self.jev_requests.append(req)
        return httpx.Response(self.jev_status, json=self.jev_answer)

    def http_client(self, handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(client.close)
        return client

    def worker(self):
        return AnalysisService(
            SpeechmaticsTranscriptor(self.settings, self.root / "jobs", self.http_client(self.speech_http), lambda _: None),
            JevAnalizador(self.settings, self.http_client(self.jev_http), lambda _: None),
            FileFragmentLedger(self.root / "fragments"), AlertsService(self.store), self.audit,
            secrets=(self.settings.speechmatics_key, self.settings.jev_key), redact_terms=("Nombre Prueba",))

    def process(self, worker=None, fragment=None, roles=True):
        f = fragment or self.fragment
        return (worker or self.worker()).process(f, roles={f"batch-{f.sequence}-S1": "patient"} if roles else {})

    def alerts(self):
        return self.db["alerts"].docs

    def test_psychology_block_transcribes_and_classifies_both_roles(self):
        self.transcript_results = [
            {"type": "word", "start_time": start, "end_time": start + 1,
             "alternatives": [{"content": text, "speaker": speaker}]}
            for start, text, speaker in (
                (0, "¿Cómo se ha sentido?", "S1"),
                (2, "Ojalá no despertar. Soy Nombre Prueba.", "S2"),
            )
        ]
        result = self.process(fragment=replace(self.fragment, analysis_unit="fragment"), roles=False)
        request = self.requests[0]
        content_type = request.headers["Content-Type"]
        multipart = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {content_type}\r\n\r\n".encode() + request.read()
        )
        config_part = next(part for part in multipart.iter_parts()
                           if part.get_param("name", header="Content-Disposition") == "config")
        config = json.loads(config_part.get_payload(decode=True))["transcription_config"]
        self.assertEqual(config["language"], "es")
        self.assertEqual(config["domain"], "medical")
        self.assertEqual(config["diarization"], "speaker")
        self.assertEqual(config["speaker_diarization_config"]["speaker_sensitivity"], 0.5)
        self.assertIn({"content": "ideación suicida"}, config["additional_vocab"])

        self.assertEqual(len(self.jev_requests), 1)
        body = json.loads(self.jev_requests[0].content)
        self.assertEqual(body["state"]["current"]["speaker_roles"], {"voz1": "unknown", "voz2": "unknown"})
        self.assertEqual([turn["speaker"] for turn in body["state"]["current"]["turns"]], ["voz1", "voz2"])
        self.assertNotIn("Nombre Prueba", json.dumps(body))
        self.assertNotIn("batch-0-S1", json.dumps(body))
        self.assertIn("entrevista psicológica", body["questions"]["signal_1"]["instructions"])
        self.assertEqual(result.decisions[0].values[1], .9)
        self.assertEqual(result.state, AnalysisState.INDETERMINATE)
        self.assertFalse(self.alerts())

    def test_typesafe_retries_only_a_confirmed_context_rejection_with_long_context(self):
        current = {"analysis_unit": "fragment", "turns": [{"text": "Diálogo sintético."}]}
        for provider in ("typesafe", "openrouter"):
            with self.subTest(provider=provider):
                requests = []
                settings = replace(self.settings, jev_provider=provider, openrouter_key="fake-openrouter-key")

                def handle(req):
                    requests.append(req)
                    if len(requests) == 1:
                        return httpx.Response(422, json={"error": {"code": "per_question_context"}})
                    return httpx.Response(200, json=answer())

                analyzer = JevAnalizador(settings, self.http_client(handle))
                if provider == "typesafe":
                    analyzer.evaluate(current, [], request_id="block-test")
                    self.assertEqual(len(requests), 2)
                    self.assertEqual(requests[1].headers["TypeSafe-Danger-Zone-Long-Context"], "true")
                    self.assertEqual(requests[1].headers["X-Request-Id"], "block-test")
                    self.assertEqual(requests[0].content, requests[1].content)
                else:
                    with self.assertRaises(JevContextLimit):
                        analyzer.evaluate(current, [])
                    self.assertEqual(len(requests), 1)
                self.assertNotIn("TypeSafe-Danger-Zone-Long-Context", requests[0].headers)

    def test_block_verifies_contextual_evidence_against_the_patient_voice(self):
        self.transcript_results = [
            {"type": "word", "start_time": start, "end_time": start + .5,
             "alternatives": [{"content": text, "speaker": speaker}]}
            for start, text, speaker in (
                (0, "¿Te has sentido así?", "S1"),
                (1, "Como ejemplo, yo preferiría no despertar.", "S1"),
                (2, "Hay días en que me gustaría no levantarme.", "S2"),
            )
        ]
        for selected, score, expected in (
            ("t2", .96, AnalysisState.SIGNAL),
            ("t1", .96, AnalysisState.INDETERMINATE),
            ("t2", .51, AnalysisState.INDETERMINATE),
        ):
            with self.subTest(selected=selected, score=score):
                def jev(request):
                    self.jev_requests.append(request)
                    body = json.loads(request.content)
                    self.assertEqual(body["state"]["current"]["speaker_roles"],
                                     {"voz1": "unknown", "voz2": "unknown"})
                    self.assertEqual(set(body["questions"]["evidencia_1_0"]["criteria"]),
                                     {"ninguno", "t1", "t2"})
                    result = answer(1)
                    for key, choice, confidence in (
                        ("evidencia_1_0", selected, score), ("evidencia_2_0", "ninguno", 1),
                        ("voz_paciente", "voz2", 1),
                    ):
                        options = body["questions"][key]["criteria"]
                        probabilities = dict.fromkeys(options, 0.)
                        probabilities[choice] = confidence
                        if choice != "ninguno":
                            probabilities["ninguno"] = 1 - confidence
                        result["answers"][key] = {"type": "choice", "choice": choice, "confidence": confidence,
                                                  "probabilities": probabilities}
                    return httpx.Response(200, json=result)

                worker = self.worker()
                worker.analyzer = JevAnalizador(self.settings, self.http_client(jev))
                fragment = replace(self.fragment, session_id=str(uuid4()), audio_test=True, analysis_unit="fragment")
                result = self.process(worker, fragment, roles=False)
                self.assertEqual(result.state, expected)
                self.assertEqual(result.decisions[0].evidence_turns["1"], ["t2"] if expected == AnalysisState.SIGNAL else [])
                if expected == AnalysisState.SIGNAL:
                    self.assertEqual(result.signals[0].start, 2.)
                    self.assertEqual(result.signals[0].speaker, "batch-0-S2")
        self.assertEqual(len(self.jev_requests), 3)
        self.assertEqual(len(self.alerts()), 1)

    def test_end_to_end_signal_typed_alert_and_delete(self):
        worker = self.worker()
        result = self.process(worker)
        self.assertIsInstance(result, AnalysisResult)
        self.assertEqual(result.contract_version, "1.0")
        self.assertEqual(result.state, AnalysisState.SIGNAL)
        self.assertEqual(result.transcription.text, self.text)
        self.assertEqual(result.transcription.words[0].speaker, "batch-0-S1")
        self.assertEqual(result.transcription.words[0].end, 1)
        self.assertEqual(self.alerts()[0]["descripcion"], self.text)
        self.assertEqual(self.alerts()[0]["nivel_severidad"], 1)
        self.assertEqual([r.method for r in self.requests], ["POST", "GET", "GET", "DELETE"])
        self.assertEqual(self.requests[2].url.params["format"], "json-v2")
        self.assertEqual(self.requests[-1].url.params["force"], "true")
        self.assertEqual(result.decisions[0].model, "jev-1.14.0")
        self.assertEqual(result.to_dict()["state"], "senal")
        journal = next((self.root / "jobs").glob("*.json")).read_text()
        self.assertNotIn(self.text, journal)
        self.assertNotIn("fake-speech-key", journal)

    def test_alert_delivery_retry_is_idempotent_even_after_worker_restart(self):
        worker = self.worker()
        result = self.process(worker)
        self.worker().register_signals(self.fragment, result)
        self.assertEqual(len(self.alerts()), 1)
        self.assertEqual(len(self.jev_requests), 1)

    def test_duplicate_and_out_of_sequence_never_call_http(self):
        worker = self.worker()
        with self.assertRaises(FragmentRejected):
            self.process(worker, replace(self.fragment, sequence=1))
        self.assertFalse(self.requests)
        self.process(worker)
        with self.assertRaises(FragmentRejected):
            self.process(worker)
        with self.assertRaises(FragmentRejected):
            self.process(self.worker())
        self.assertEqual(len(self.jev_requests), 1)

    def test_context_stays_in_session_and_is_bounded(self):
        worker = self.worker()
        self.process(worker)
        self.process(worker, replace(self.fragment, sequence=1))
        second_state = json.loads(self.jev_requests[-1].content)["state"]
        self.assertEqual(len(second_state["history"]), 1)
        other = replace(self.fragment, session_id=str(uuid4()))
        self.process(worker, other)
        self.assertEqual(json.loads(self.jev_requests[-1].content)["state"]["history"], [])
        self.process(worker, replace(self.fragment, sequence=2, start=32 * 16000, end=33 * 16000,
                                     context_start=32 * 16000, path=self._long_audio()))
        self.process(worker, replace(self.fragment, sequence=3, start=96 * 16000, end=97 * 16000,
                                     context_start=96 * 16000, path=self._long_audio()))
        self.assertEqual(json.loads(self.jev_requests[-1].content)["state"]["history"], [])
        worker.close_session(other.session_id)
        self.assertNotIn(other.session_id, worker.histories)

    def _long_audio(self):
        path = self.root / "long.pcm"
        if not path.exists():
            path.write_bytes(b"\0\0" * 100 * 16000)
        return path

    def test_redaction_removes_identifiers_paths_credentials_and_pii(self):
        self.text = (f"Nombre Prueba {self.fragment.session_id} {self.audio} "
                     "C:\\privado\\audio.wav /var/privado.wav fake-jev-key fake-speech-key "
                     "persona@example.test 12.345.678-5 +56912345678 token=secreto")
        self.jev_answer = answer()
        self.process()
        body = self.jev_requests[0].content.decode()
        for forbidden in [self.fragment.session_id, str(self.audio), "Nombre Prueba", "persona@example.test",
                          "12.345.678-5", "+56912345678", "fake-jev-key", "fake-speech-key", "secreto", "privado"]:
            self.assertNotIn(forbidden, body)
        self.assertEqual(set(json.loads(body)), {"model", "state", "questions"})
        self.assertEqual(set(json.loads(body)["state"]["current"]), {"text", "start", "end", "role"})

    def test_no_risk_does_not_create_alert(self):
        self.text, self.jev_answer = "Hoy estoy bien", answer()
        result = self.process()
        self.assertEqual(result.state, AnalysisState.NO_SIGNAL)
        self.assertEqual(self.alerts(), [])

    def test_unknown_speaker_role_is_indeterminate(self):
        self.assertEqual(self.process(roles=False).state, AnalysisState.INDETERMINATE)
        self.assertEqual(self.alerts(), [])

    def test_ambiguous_context_is_indeterminate(self):
        self.jev_answer = answer(1, "pregunta")
        self.assertEqual(self.process().state, AnalysisState.INDETERMINATE)
        self.assertEqual(self.alerts(), [])

    def test_speech_failure_and_jev_failure_write_sanitized_bitacora(self):
        for provider in ["speech", "jev"]:
            with self.subTest(provider=provider):
                f = replace(self.fragment, session_id=str(uuid4()))
                self.post_status = 401 if provider == "speech" else 201
                self.jev_status = 401 if provider == "jev" else 200
                with self.assertLogs("psycode.audit", level="INFO") as logs:
                    result = self.process(fragment=f)
                self.assertEqual(result.state, AnalysisState.INDETERMINATE)
                event = self.db["audit_events"].docs[-1]
                self.assertEqual(event["action"], "analysis.speechmatics" if provider == "speech" else "analysis.jev")
                self.assertIsNone(event["alerta_id"])
                self.assertNotIn(self.text, json.dumps(event, default=str) + str(logs.output))
        self.assertFalse(self.alerts())

    def test_invalid_transcript_is_deleted_and_indeterminate(self):
        self.invalid_transcript = True
        result = self.process()
        self.assertEqual(result.state, AnalysisState.INDETERMINATE)
        self.assertEqual(self.requests[-1].method, "DELETE")
        self.assertFalse(self.jev_requests)

    def test_delete_failure_is_partial_and_never_alerts(self):
        self.delete_status = 403
        result = self.process()
        self.assertEqual(result.state, AnalysisState.INDETERMINATE)
        self.assertIn("SPEECHMATICS_DELETE_PENDING", result.error_codes)
        self.assertFalse(self.alerts())
        self.assertEqual(self.db["audit_events"].docs[-1]["error_code"], "SPEECHMATICS_DELETE_PENDING")

    def test_uncertain_speechmatics_submission_is_not_retried(self):
        self.post_status = 503
        worker = self.worker()
        self.assertEqual(self.process(worker).state, AnalysisState.INDETERMINATE)
        self.assertEqual(len(self.requests), 1)
        with self.assertRaises(FragmentRejected):
            self.process(self.worker())
        journal = json.loads(next((self.root / "jobs").glob("*.json")).read_text())
        self.assertEqual(journal["state"], "uncertain")

    def test_uncertain_jev_submission_is_not_retried(self):
        self.jev_status = 503
        result = self.process()
        self.assertIn("JEV_SUBMISSION_UNCERTAIN", result.error_codes)
        self.assertEqual(len(self.jev_requests), 1)
        self.assertFalse(self.alerts())

    def test_wrong_model_is_indeterminate_and_no_alert(self):
        self.jev_answer["model"] = "jev-latest"
        self.assertEqual(self.process().state, AnalysisState.INDETERMINATE)
        self.assertFalse(self.alerts())

    def test_unconfirmed_high_level_is_not_reported_as_no_risk(self):
        self.text, self.jev_answer = "Estoy cansado", answer(5)
        self.assertEqual(self.process().state, AnalysisState.INDETERMINATE)

    def test_alert_levels_follow_existing_operational_scale(self):
        for level, text, severity in [
            (2, "Pienso en suicidarme", 1),
            (4, "Tengo intención de suicidarme", 2),
            (5, "Tengo un plan de suicidio y tengo intención de actuar", 3)]:
            with self.subTest(level=level):
                self.text, self.jev_answer = text, answer(level)
                result = self.process(fragment=replace(self.fragment, session_id=str(uuid4())))
                self.assertEqual(result.state, AnalysisState.SIGNAL)
                self.assertIn(severity, [s.severity for s in result.signals])
                self.assertTrue(all(1 <= a["nivel_severidad"] <= 3 for a in self.alerts()))

    def test_composition_creates_no_process_or_network(self):
        with patch("subprocess.Popen", side_effect=AssertionError("No procesos auxiliares")):
            worker = analysis_worker(settings=self.settings, directory=self.root,
                                     speechmatics_http=self.http_client(self.speech_http),
                                     jev_http=self.http_client(self.jev_http), alert_store=self.store, audit=self.audit)
            result = self.process(worker)
        self.assertEqual(result.state, AnalysisState.SIGNAL)

    def test_disabled_external_processing_never_reads_audio_or_calls_http(self):
        self.settings = replace(self.settings, external_enabled=False)
        self.audio.unlink()
        self.assertEqual(self.process().state, AnalysisState.INDETERMINATE)
        self.assertFalse(self.requests)

    def test_default_composition_reaches_bitacora_before_task_closure(self):
        self.post_status = 401
        with patch("backend.apps.alerts.mongo.get_database", return_value=self.db):
            worker = analysis_worker(settings=self.settings, directory=self.root,
                                     speechmatics_http=self.http_client(self.speech_http),
                                     jev_http=self.http_client(self.jev_http), alert_store=self.store)
            result = self.process(worker)
        self.assertEqual(result.state, AnalysisState.INDETERMINATE)
        self.assertEqual(self.db["audit_events"].docs[-1]["action"], "analysis.speechmatics")

    def test_partial_jev_result_is_indeterminate_even_with_one_valid_signal(self):
        self.transcript_results = [
            {"type": "word", "start_time": i, "end_time": i + 1,
             "alternatives": [{"content": self.text + ".", "speaker": "S1"}]} for i in range(2)]
        count = 0
        def partial(req):
            nonlocal count
            count += 1
            return httpx.Response(200 if count == 1 else 401, json=answer(1))
        worker = self.worker()
        worker.analyzer = JevAnalizador(self.settings, self.http_client(partial))
        result = self.process(worker)
        self.assertEqual(result.state, AnalysisState.INDETERMINATE)
        self.assertTrue(result.signals)
        self.assertFalse(self.alerts())

    def test_empty_transcript_is_indeterminate_without_calling_jev(self):
        self.transcript_results = []
        self.assertEqual(self.process().state, AnalysisState.INDETERMINATE)
        self.assertFalse(self.jev_requests)

    def test_unavailable_bitacora_uses_sanitized_fallback(self):
        def unavailable():
            raise RuntimeError("provider response and secrets")
        with self.assertLogs("psycode.audit", level="INFO") as logs:
            AnalysisAudit(unavailable).failure("JEV_FAILED")
        self.assertIn("AUDIT_UNAVAILABLE", str(logs.output))
        self.assertNotIn("provider response", str(logs.output))

    def test_restart_does_not_silently_resume_with_missing_context(self):
        self.process()
        with self.assertRaises(FragmentRejected):
            self.process(self.worker(), replace(self.fragment, sequence=1))


class ContractTests(SimpleTestCase):
    def test_invalid_jev_structures_rejected(self):
        mutations = [lambda a: a.update(model="jev-2.0.0"),
                     lambda a: a["answers"].pop("signal_7"),
                     lambda a: a["answers"]["signal_1"].update(noul=True),
                     lambda a: a["answers"]["signal_1"].update(noul=float("nan")),
                     lambda a: a["answers"]["signal_1"].update(noul=2),
                     lambda a: a["answers"]["signal_1"].update(type="choice"),
                     lambda a: a["usage"].update(input_tokens=-1),
                     lambda a: a["usage"].update(output_tokens=True),
                     lambda a: a["answers"]["context"]["probabilities"].update(pregunta=1)]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                payload = answer()
                mutation(payload)
                with self.assertRaises(ProviderError):
                    validate_response(payload, "jev-1.14.0")

    def test_openrouter_dated_alias_and_optional_metrics(self):
        payload = answer(model="typesafe/jev-1.13-20260917")
        payload["answers"]["context"].pop("confidence")
        payload["answers"]["context"].pop("probabilities")
        validate_response(payload, "typesafe/jev-1.13", "openrouter")
        for model in ["typesafe/jev-1.14", "typesafe/jev-1.13-20269999", "other/jev-1.13"]:
            payload["model"] = model
            with self.assertRaises(ProviderError):
                validate_response(payload, "typesafe/jev-1.13", "openrouter")

    def test_post_transport_error_has_one_attempt(self):
        calls = []
        def fail(req):
            calls.append(req)
            raise httpx.ReadTimeout("sensitive content")
        with httpx.Client(transport=httpx.MockTransport(fail)) as client:
            with self.assertRaises(SubmissionUncertain):
                request(client, "POST", "https://example.test", safe=False)
        self.assertEqual(len(calls), 1)

    def test_rate_limit_refusal_can_retry_without_uncertain_resubmission(self):
        codes, delays = iter([429, 200]), []
        with httpx.Client(transport=httpx.MockTransport(
                lambda _: httpx.Response(next(codes), headers={"Retry-After": "0"}))) as client:
            self.assertEqual(request(client, "POST", "https://example.test", safe=False,
                                     sleep=delays.append).status_code, 200)
        self.assertEqual(delays, [0.])

    def test_environment_configuration_uses_only_supplied_variables(self):
        with patch.dict("os.environ", {"SPEECHMATICS_API_KEY": "fake", "TYPESAFE_API_KEY": "fake",
                                     "PSYCODE_EXTERNAL_PROCESSING_ENABLED": "1"}, clear=True):
            settings = Settings.from_env()
            settings.validate("speechmatics")
            settings.validate("jev")
            self.assertNotIn("fake", repr(settings))
            with self.assertRaises(ProviderError):
                replace(settings, jev_model="jev-latest").validate("jev")
