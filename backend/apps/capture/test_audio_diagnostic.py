from datetime import timedelta
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
import httpx
from rest_framework.test import APIClient

from backend.apps.analysis.providers.settings import Settings
from backend.apps.analysis.tests.test_integration import plain_answer
from backend.apps.alerts.repositories import AlertsRepository
from backend.apps.alerts.services import AlertsService
from backend.apps.alerts.tests.test_persistence import FakeDatabase
from backend.apps.operational.models import OperationalConfiguration
from backend.config.composition import fragment_job_processor
from .models import AgentCommand, AgentRegistration, FragmentJob
from .retention import purge_checkpoints
from .test_ingestion import wav_bytes


class AudioDiagnosticTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        config = override_settings(CAPTURE_FRAGMENT_ROOT=self.root / "audio")
        config.enable()
        self.addCleanup(config.disable)
        self.agent = self.new_agent(self.client)

    def new_agent(self, client):
        agent = uuid4()
        token = f"{agent}." + "a" * 43
        AgentRegistration.objects.create(pk=agent, box="box-3", name="PC sintético",
                                         token_sha256=hashlib.sha256(token.encode()).hexdigest())
        client.defaults["HTTP_AUTHORIZATION"] = "Agent " + token
        return agent

    def start(self, scenario, samples=16000):
        ident = str(uuid4())
        url = f"/api/v2/internal/audio-tests/{ident}"
        payload = {"scenario": scenario, "samples": samples}
        response = self.client.put(url, payload, content_type="application/json")
        self.assertEqual(response.status_code, 201, response.json())
        data = response.json()["data"]
        self.assertEqual(self.client.put(url, payload, content_type="application/json").json()["data"], data)
        return url, data

    def upload(self, url, data, *, seq=0, offset=0, end=16000, new=0, **changes):
        wav = wav_bytes(b"\x01\x00" * (end - offset))
        started = timezone.datetime.fromisoformat(data["started_at"])
        payload = dict(
            archivo=SimpleUploadedFile("clip-ficticio.wav", wav, "audio/wav"),
            box="box-3", session_id=data["test_id"], secuencia=seq, formato="wav",
            checksum=hashlib.sha256(wav).hexdigest(),
            captured_at=(started + timedelta(seconds=offset / 16000)).isoformat(),
            session_start_sample=offset, session_end_sample=end, new_audio_start_sample=new,
            sample_rate=16000, chunk_samples=160000, overlap_samples=16000,
        )
        payload.update(changes)
        now = max(timezone.now(), started + timedelta(seconds=end / 16000))
        with patch("django.utils.timezone.now", return_value=now):
            return self.client.post(url, payload)

    def test_authorization_is_scoped_to_test_and_to_the_same_pc(self):
        url, data = self.start("neutral")
        other = APIClient()
        self.new_agent(other)
        self.assertEqual(other.get(url).status_code, 404)
        self.assertEqual(other.post(url + "/fragments").status_code, 404)
        self.assertEqual(APIClient().get(url).status_code, 401)
        self.assertEqual(self.upload("/api/v2/internal/fragments", data).status_code, 404)
        self.assertEqual(self.upload(url + "/fragments", data, seq=1).status_code, 409)
        self.assertEqual(self.upload(url + "/fragments", data, end=8000).status_code, 422)
        clinical = self.client.get("/api/v2/internal/sessions/" + data["test_id"])
        self.assertEqual(clinical.json()["error"]["code"], "SESSION_NOT_FOUND")
        self.assertFalse(AgentCommand.objects.exists())
        self.assertFalse(FragmentJob.objects.exists())

    def test_fragment_details_show_progress_outcomes_and_reason_after_cleanup(self):
        url, data = self.start("alerta", samples=28 * 16000)
        detail_url = url + "?fragment_details=1"
        self.assertNotIn("fragments", data)
        self.assertEqual(self.client.get(detail_url).json()["data"]["fragments"], [])
        self.assertEqual(self.client.get(url + "?fragment_details=2").status_code, 400)
        intervals = [(0, 10), (9, 19), (18, 28)]
        for seq, (start, end) in enumerate(intervals):
            response = self.upload(url + "/fragments", data, seq=seq, offset=start * 16000,
                                   end=end * 16000, new=(intervals[seq - 1][1] * 16000 if seq else 0))
            self.assertEqual(response.status_code, 201, response.json())
        jobs = list(FragmentJob.objects.order_by("sequence__number"))
        FragmentJob.objects.filter(pk=jobs[1].pk).update(state=FragmentJob.State.PROCESSING)
        progress = self.client.get(detail_url).json()["data"]
        self.assertEqual([row["status"] for row in progress["fragments"]], ["queued", "analyzing", "queued"])
        self.assertEqual(progress["analyzed"], 0)

        outcomes = [FragmentJob.Result.NO_RISK_DETECTED, FragmentJob.Result.RISK_DETECTED,
                    FragmentJob.Result.INDETERMINATE]
        for job, result in zip(jobs, outcomes, strict=True):
            FragmentJob.objects.filter(pk=job.pk).update(state=FragmentJob.State.COMPLETED, result=result)
        FragmentJob.objects.filter(pk=jobs[-1].pk).update(checkpoint={
            "block_result": {"error_codes": ["CONTEXT_NOT_EVALUABLE"], "decisions": ["detalle interno"]},
        })
        complete = self.client.get(detail_url).json()["data"]
        self.assertEqual(complete["fragments"], [
            {"sequence": 0, "start_sample": 0, "end_sample": 160000, "status": "no_signal"},
            {"sequence": 1, "start_sample": 144000, "end_sample": 304000, "status": "signal"},
            {"sequence": 2, "start_sample": 288000, "end_sample": 448000, "status": "indeterminate",
             "reason": "CONTEXT_NOT_EVALUABLE"},
        ])
        self.assertNotIn("fragments", self.client.get(url).json()["data"])
        purge_checkpoints(jobs[-1].sequence.accepted_at + timedelta(minutes=2))
        self.assertEqual(self.client.get(detail_url).json()["data"], complete)
        jobs[-1].refresh_from_db()
        self.assertEqual(jobs[-1].checkpoint, {"test_error_codes": ["CONTEXT_NOT_EVALUABLE"]})

    @override_settings(NOTIFICATIONS_ENABLED=True, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_clip_persists_and_emails_only_detected_test_alerts(self):
        config = OperationalConfiguration.load()
        config.primary_email = "demo@example.test"
        config.save()
        db = FakeDatabase()
        store = AlertsRepository(db)
        settings = Settings(speechmatics_key="test-speech-key", jev_key="test-jev-key", external_enabled=True)
        sent_to_jev, provider_calls = [], []
        text = ""
        signal = None

        def speech(request):
            provider_calls.append(request.method)
            if request.method == "POST":
                return httpx.Response(201, json={"id": "synthetic-job"})
            if request.method == "DELETE":
                return httpx.Response(200)
            if request.url.path.endswith("/transcript"):
                return httpx.Response(200, json={"results": [{
                    "type": "word", "start_time": 0, "end_time": 0.8,
                    "alternatives": [{"content": text, "speaker": "S1"}],
                }]})
            return httpx.Response(200, json={"job": {"status": "done"}})

        def jev(request):
            sent_to_jev.append(request.content)
            questions = json.loads(request.content)["questions"]
            return httpx.Response(200, json=plain_answer(questions, {"t0": (f"nivel_{signal}", .9)} if signal else {}))

        with (httpx.Client(transport=httpx.MockTransport(speech)) as speech_client,
              httpx.Client(transport=httpx.MockTransport(jev)) as jev_client):
            processor = fragment_job_processor(settings=settings, directory=self.root,
                                               speechmatics_http=speech_client, jev_http=jev_client,
                                               alert_store=store, audit=Mock())
            for scenario, text, signal, expected in [
                ("neutral", "Me gusta tomar café por la mañana", None, 0),
                ("alerta", "Ojalá no despertar", 1, 1),
            ]:
                with self.subTest(scenario=scenario):
                    url, data = self.start(scenario)
                    self.assertEqual(data["state"], "receiving")
                    first = self.upload(url + "/fragments", data)
                    self.assertEqual(first.status_code, 201, first.json())
                    retry = self.upload(url + "/fragments", data)
                    self.assertEqual(retry.status_code, 200, retry.json())
                    self.assertEqual(first.json()["data"], retry.json()["data"])
                    self.assertEqual(self.client.get(url).json()["data"]["state"], "analyzing")
                    if expected:
                        # El worker perdió la confirmación final después de enviar el correo.
                        with patch.object(processor, "_finish_completed", return_value=None):
                            self.assertIsNone(processor.process_next())
                        self.assertEqual(len(mail.outbox), 1)
                        processor.recover_stuck(now=timezone.now() + timedelta(minutes=6))
                    self.assertEqual(processor.process_next(), FragmentJob.State.COMPLETED)
                    finished = self.client.get(url).json()["data"]
                    self.assertEqual(finished["state"], "completed")
                    self.assertEqual(finished["accepted"], 1)
                    self.assertEqual(finished["analyzed"], 1)
                    self.assertEqual(finished["indeterminate"], 0)
                    self.assertEqual(len(finished["alerts"]), expected)
                    self.assertNotIn(text, str(finished))
                    job = FragmentJob.objects.get(sequence__session_id=data["test_id"])
                    self.assertIn("speechmatics", job.checkpoint)
                    purge_checkpoints(job.sequence.accepted_at + timedelta(minutes=2))
                    job.refresh_from_db()
                    self.assertEqual(job.checkpoint, {"test_alerts": finished["alerts"]} if expected else {})
                    self.assertEqual(self.client.get(url).json()["data"], finished)
                    self.assertEqual(len(db["alerts"].docs), expected)
                    self.assertEqual(len(mail.outbox), expected)
                    self.assertIsNone(processor.process_next())
                    self.assertEqual(len(mail.outbox), expected)
                    if expected:
                        alert_id = finished["alerts"][0]["id"]
                        self.assertEqual(store.get_alert(alert_id).sesion_id, data["test_id"])
                        self.assertEqual(store.get_alert(alert_id).descripcion, text)
                        message = mail.outbox[0]
                        self.assertEqual(message.to, ["demo@example.test"])
                        self.assertTrue(message.subject.startswith("[PRUEBA]"))
                        for body in (message.body, message.alternatives[0].content):
                            self.assertIn("ALERTA DE PRUEBA", body)
                            self.assertIn("No requiere intervención clínica.", body)
                            self.assertNotIn(text, body)
                        browser = APIClient()
                        browser.force_authenticate(user=SimpleNamespace(
                            is_authenticated=True, pk=uuid4(), username="supervisor-sintetico",
                        ))
                        detail = "/api/v1/alerts/" + alert_id
                        with patch("backend.apps.alerts.views.get_service", return_value=AlertsService(store)):
                            alert_detail = browser.get(detail).json()["data"]
                            self.assertIs(alert_detail["es_prueba"], True)
                            self.assertEqual(alert_detail["descripcion"], text)
                            response = browser.post(detail + "/evaluacion", {"evaluacion": "correcta"}, format="json")
                            self.assertEqual(response.status_code, 201, response.json())
                            reviewed = browser.get(detail).json()["data"]
                            self.assertEqual(reviewed["estado_evaluacion"], "correcta")
                            self.assertIs(reviewed["es_prueba"], True)
        self.assertEqual(provider_calls, ["POST", "GET", "GET", "DELETE"] * 2)
        self.assertEqual(len(sent_to_jev), 2)

    def test_ten_minute_test_can_stop_and_restart_at_another_position(self):
        url, data = self.start("alerta", samples=16000 * 600)
        self.assertEqual(data["expected"], 67)
        started = timezone.datetime.fromisoformat(data["started_at"])
        other = APIClient()
        self.new_agent(other)
        self.assertEqual(other.delete(url).status_code, 404)
        with patch("django.utils.timezone.now", return_value=started + timedelta(minutes=6)):
            first = self.upload(url + "/fragments", data, end=160000)
            self.assertEqual(first.status_code, 201, first.json())
            stopped = self.client.delete(url).json()["data"]
            self.assertEqual((stopped["state"], stopped["accepted"]), ("stopped", 1))
            self.assertEqual(self.client.delete(url).json()["data"], stopped)
            self.assertEqual(self.upload(url + "/fragments", data, end=160000).status_code, 200)
            late = self.upload(url + "/fragments", data, seq=1, offset=144000, end=304000, new=160000)
            self.assertEqual(late.json()["error"]["code"], "AUDIO_TEST_EXPIRED")
            _, resumed = self.start("alerta", samples=16000 * 120)
            self.assertNotEqual(resumed["test_id"], data["test_id"])
        self.assertEqual(FragmentJob.objects.count(), 1)
        self.assertFalse(AgentCommand.objects.exists())

    def test_negotiated_profiles_upload_partial_tail_and_retry_unchanged(self):
        from .models import CaptureSession
        for mode, seconds, samples, expected in [
            ("fixed", 600, 600 * 16000, 1),
            ("fixed", 60, 600 * 16000, 11),
            ("session", 60, 600 * 16000, 1),
            ("fixed", 600, 23 * 16000 + 1, 1),
            ("fixed", 600, 8000, 1),
        ]:
            with self.subTest(mode=mode, seconds=seconds, samples=samples):
                config = OperationalConfiguration.load()
                config.audio_chunk_duration = seconds
                config.audio_chunk_mode = mode
                config.save()
                url = f"/api/v2/internal/audio-tests/{uuid4()}"
                payload = {"scenario": "neutral", "samples": samples}
                query = url + "?fragment_profile_version=1"
                response = self.client.put(query, payload, content_type="application/json")
                self.assertEqual(response.status_code, 201, response.json())
                data = response.json()["data"]
                self.assertEqual(data["fragment_profile_version"], 1)
                self.assertEqual(data["expected"], expected)
                effective = max(10, (samples + 15999) // 16000)
                if mode == "fixed":
                    effective = min(seconds, effective)
                self.assertEqual(data["audio_chunk_duration"], effective)
                session = CaptureSession.objects.get(pk=data["test_id"])
                self.assertIsNone(session.capture_chunk_negotiated)
                self.assertEqual(session.capture_chunk_config["audio_chunk_duration"], seconds)
                config.audio_chunk_duration = 10
                config.save()
                self.assertEqual(self.client.put(query, payload, content_type="application/json").json()["data"], data)
                self.assertEqual(self.client.put(url, payload, content_type="application/json").status_code, 409)
                chunk = effective * 16000
                step = chunk - 16000
                for seq in range(expected):
                    offset = seq * step
                    end = min(offset + chunk, samples)
                    new = 0 if seq == 0 else offset + 16000
                    args = dict(seq=seq, offset=offset, end=end, new=new, chunk_samples=chunk)
                    first = self.upload(url + "/fragments", data, **args)
                    self.assertEqual(first.status_code, 201, first.json())
                    retry = self.upload(url + "/fragments", data, **args)
                    self.assertEqual(retry.status_code, 200, retry.json())
                    self.assertEqual(first.json()["data"], retry.json()["data"])
                status = self.client.get(url).json()["data"]
                self.assertEqual(status["accepted"], expected)
                self.assertEqual(status["audio_chunk_duration"], effective)
                self.assertEqual(self.client.delete(url).json()["data"]["fragment_profile_version"], 1)
        self.assertFalse(AgentCommand.objects.exists())

    def test_profile_query_is_strict_and_legacy_cannot_upgrade(self):
        url = f"/api/v2/internal/audio-tests/{uuid4()}"
        payload = {"scenario": "neutral", "samples": 16000}
        for query in ["", "0", "3", "01", "true", "1&fragment_profile_version=1", "1&fragment_profile_version=2"]:
            response = self.client.put(url + "?fragment_profile_version=" + query,
                                       payload, content_type="application/json")
            self.assertEqual(response.status_code, 400, response.json())
        legacy = self.client.put(url, payload, content_type="application/json")
        self.assertEqual(legacy.status_code, 201)
        self.assertNotIn("fragment_profile_version", legacy.json()["data"])
        self.assertEqual(self.client.put(url + "?fragment_profile_version=1", payload,
                                         content_type="application/json").status_code, 409)

    def test_profile_contract_has_canonical_hash_and_required_negotiation_fields(self):
        import json
        from django.conf import settings
        contracts = Path(settings.BASE_DIR) / "contracts"
        name = "audio-test-profile-v1.schema.json"
        raw = (contracts / name).read_bytes()
        manifest = json.loads((contracts / "manifest.json").read_text())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), manifest["sha256"][name])
        schema = json.loads(raw)
        response = schema["$defs"]["response"]
        self.assertIn("fragment_profile_version", response["required"])
        self.assertIn("audio_chunk_duration", response["required"])
        self.assertEqual(response["properties"]["fragment_profile_version"]["const"], 1)
        self.assertEqual(schema["$defs"]["query"]["properties"]["fragment_profile_version"]["const"], "1")

    def test_v2_profiles_have_no_overlap_and_cannot_switch_version(self):
        from .models import CaptureSession
        for seconds, samples, expected in [(600, 600 * 16000, 1), (60, 600 * 16000, 10),
                                            (60, 61 * 16000 + 1, 2)]:
            with self.subTest(seconds=seconds, samples=samples):
                config = OperationalConfiguration.load()
                config.audio_chunk_duration = seconds
                config.save()
                url = f"/api/v2/internal/audio-tests/{uuid4()}"
                query = url + "?fragment_profile_version=2"
                payload = {"scenario": "neutral", "samples": samples}
                response = self.client.put(query, payload, content_type="application/json")
                self.assertEqual(response.status_code, 201, response.json())
                data = response.json()["data"]
                self.assertEqual(data["fragment_profile_version"], 2)
                self.assertEqual(data["audio_chunk_overlap"], 0)
                self.assertEqual(data["expected"], expected)
                session = CaptureSession.objects.get(pk=data["test_id"])
                saved = session.capture_chunk_config.copy()
                self.assertEqual(saved["analysis_unit"], "fragment")
                self.assertEqual(saved["audio_chunk_overlap"], 0)
                self.assertEqual(self.client.put(url + "?fragment_profile_version=1", payload,
                                                content_type="application/json").status_code, 409)
                config.audio_chunk_duration = 10
                config.save()
                self.assertEqual(self.client.put(query, payload, content_type="application/json").json()["data"], data)
                chunk = data["audio_chunk_duration"] * 16000
                for seq in range(expected):
                    offset = seq * chunk
                    end = min(offset + chunk, samples)
                    args = dict(seq=seq, offset=offset, end=end, new=offset,
                                chunk_samples=chunk, overlap_samples=0)
                    first = self.upload(url + "/fragments", data, **args)
                    self.assertEqual(first.status_code, 201, first.json())
                    retry = self.upload(url + "/fragments", data, **args)
                    self.assertEqual(retry.status_code, 200, retry.json())
                    self.assertEqual(first.json()["data"], retry.json()["data"])
                self.assertEqual(FragmentJob.objects.filter(sequence__session=session).count(), expected)
                status = self.client.get(url).json()["data"]
                self.assertEqual(status["accepted"], expected)
                self.assertEqual(status["audio_chunk_overlap"], 0)
                self.assertEqual(self.client.delete(url).json()["data"]["fragment_profile_version"], 2)
                session.refresh_from_db()
                self.assertEqual(session.capture_chunk_config, saved)
