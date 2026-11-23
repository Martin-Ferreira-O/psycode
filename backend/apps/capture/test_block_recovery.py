"""Una decisión conjunta no se repite al recuperar su entrega."""
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

from django.test import SimpleTestCase
from backend.apps.analysis.domain import AnalysisState, Fragment, JevDecision
from backend.apps.analysis.errors import AnalysisRetry, SubmissionUncertain
from backend.apps.analysis.services import AnalysisService
from backend.common.errors import PersistenceUnavailable


class Checkpoint:
    def __init__(self):
        self.data = {"speechmatics": {"state": "deleted"}, "roles": {"S1": "patient", "S2": "professional"},
                     "utterances": [
                         {"text": "Ojalá no despertar", "start": 1., "end": 2., "speaker": "S1", "attribution": "assigned"},
                         {"text": "¿Cómo estás?", "start": 20., "end": 21., "speaker": "S2", "attribution": "assigned"},
                         {"text": "Ojalá no despertar", "start": 40., "end": 41., "speaker": "S1", "attribution": "assigned"}]}
        self.interrupt = False
    def save(self):
        if self.interrupt and "jev_response" in self.data and "result" not in self.data:
            self.interrupt = False
            raise RuntimeError("Corte tras persistir respuesta")


class BlockRecoveryTests(SimpleTestCase):
    def setUp(self):
        self.analyzer, self.alerts = Mock(), Mock()
        self.analyzer.evaluate.return_value = JevDecision(
            "simulated", "afirmacion_propia", (.1, .9, .1, .1, .1, .1, .1, .1), 10, 1,
            evidence_turns={"1": ["t0", "t2"]},
            text_evidence={"t0": {"choice": "nivel_1", "score": .9}, "t2": {"choice": "nivel_1", "score": .9}},
        )
        self.fragment = Fragment(str(uuid4()), 0, "box-3", datetime.now(timezone.utc), Path("synthetic.wav"),
                                 end=600 * 16000, analysis_unit="fragment")
        self.checkpoint = Checkpoint()
    def service(self):
        return AnalysisService(Mock(), self.analyzer, Mock(), self.alerts, Mock())
    def resume(self):
        return self.service().resume(self.fragment, roles={}, checkpoint=self.checkpoint, previous={})
    def test_many_turns_produce_one_decision_one_alert_and_persisted_scores(self):
        result, context = self.resume()
        self.assertEqual(self.analyzer.evaluate.call_count, 1)
        self.assertEqual(len(result.decisions), 1)
        self.assertEqual(len(result.signals), 2)
        self.assertEqual(self.alerts.register_alert.call_count, 1)
        current = self.analyzer.evaluate.call_args.args[0]
        self.assertEqual(current["text"].splitlines()[1], "[t1] ¿Cómo estás?")
        self.assertNotIn("speaker_roles", current)
        self.assertEqual(len(context["block_result"]["decisions"]), 1)
        self.assertNotIn("text", context["block_result"])
    def test_saved_provider_response_survives_restart_without_reclassification(self):
        self.checkpoint.interrupt = True
        with self.assertRaises(RuntimeError):
            self.resume()
        result, _ = self.resume()
        self.assertEqual(len(result.decisions), 1)
        self.assertEqual(self.analyzer.evaluate.call_count, 1)
        self.assertEqual(self.alerts.register_alert.call_count, 1)
    def test_uncertain_submission_is_not_repeated_after_restart(self):
        self.analyzer.evaluate.side_effect = SubmissionUncertain("Respuesta perdida")
        for _ in range(2):
            with self.assertRaises(AnalysisRetry) as error:
                self.resume()
            self.assertEqual(error.exception.code, "JEV_SUBMISSION_UNCERTAIN")
        self.assertEqual(self.analyzer.evaluate.call_count, 1)
        self.alerts.register_alert.assert_not_called()
    def test_failed_alert_persistence_reuses_classification(self):
        self.alerts.register_alert.side_effect = PersistenceUnavailable()
        with self.assertRaises(PersistenceUnavailable):
            self.resume()
        self.alerts.register_alert.side_effect = None
        self.resume()
        self.assertEqual(self.analyzer.evaluate.call_count, 1)
        self.assertEqual(self.alerts.register_alert.call_count, 2)

    def test_clinical_and_test_audio_share_the_same_processing(self):
        from dataclasses import replace
        self.checkpoint.data["roles"] = {}
        clinical, _ = self.resume()
        self.checkpoint = Checkpoint()
        self.checkpoint.data["roles"] = {}
        self.fragment = replace(self.fragment, audio_test=True)
        synthetic, context = self.resume()
        self.assertEqual(synthetic.signals, clinical.signals)
        self.assertEqual(len(context["test_alerts"]), 1)

    def test_saved_review_response_resumes_without_resubmission_or_duplicate_alert(self):
        self.checkpoint.data["roles"] = {}
        self.checkpoint.data["utterances"] = [
            {"text": "Me quiero matar.", "start": 1., "end": 2., "speaker": None, "attribution": "unknown"},
        ]
        self.analyzer.evaluate.return_value = JevDecision(
            "simulated", "afirmacion_propia", (.1, .1, .9, .1, .1, .1, .1, .1), 10, 1, {"2": ["t0"]},
            text_evidence={"t0": {"choice": "nivel_2", "score": .9}},
        )
        self.checkpoint.interrupt = True
        with self.assertRaises(RuntimeError):
            self.resume()
        recovered, _ = self.resume()
        delivered, _ = self.resume()
        self.assertEqual(recovered.state, AnalysisState.SIGNAL)
        self.assertEqual(recovered.signals, delivered.signals)
        self.assertIsNone(recovered.signals[0].speaker)
        self.analyzer.evaluate.assert_called_once()
        self.alerts.register_alert.assert_called_once()
        self.assertEqual(self.alerts.register_alert.call_args.kwargs["origen"], "analysis.speechmatics-jev/1.0")

    def test_saved_legacy_response_does_not_create_unattributed_evidence(self):
        self.checkpoint.data["roles"] = {}
        self.checkpoint.data["jev_pending"] = {
            "request_id": "legacy-request", "questions_version": "bloque-signals-3",
        }
        self.checkpoint.data["jev_response"] = asdict(self.analyzer.evaluate.return_value)
        result, context = self.resume()
        self.assertEqual(result.state, AnalysisState.INDETERMINATE)
        self.assertEqual(context["block_result"]["questions_version"], "bloque-signals-3")
        self.analyzer.evaluate.assert_not_called()
        self.alerts.register_alert.assert_not_called()

    def test_saved_version_four_evidence_remains_usable_after_upgrade(self):
        self.checkpoint.data["roles"] = {}
        self.checkpoint.data["utterances"] = [
            {"text": "Me quiero matar.", "start": 1., "end": 2., "speaker": None, "attribution": "unknown"},
        ]
        self.checkpoint.data["jev_pending"] = {
            "request_id": "legacy-review-request", "questions_version": "bloque-signals-4",
        }
        self.checkpoint.data["jev_response"] = {
            "model": "simulated", "context": "afirmacion_propia", "values": [.1, .1, .9, .1, .1, .1, .1, .1],
            "input_tokens": 10, "output_tokens": 1, "evidence_turns": {"2": ["t0"]},
        }
        result, _ = self.resume()
        self.assertEqual(result.state, AnalysisState.SIGNAL)
        self.assertEqual(result.questions_version, "bloque-signals-4")
        self.analyzer.evaluate.assert_not_called()
        self.alerts.register_alert.assert_called_once()

    def test_retry_reuses_the_grouped_alert_with_both_verified_signals(self):
        self.checkpoint.data["roles"] = {}
        self.checkpoint.data["utterances"] = [
            {"text": "He pensado en quitarme la vida.", "start": 0., "end": 1., "speaker": None, "attribution": "unknown"},
            {"text": "Me voy a matar mañana.", "start": 2., "end": 3., "speaker": None, "attribution": "unknown"},
        ]
        self.analyzer.evaluate.return_value = JevDecision(
            "simulated", "afirmacion_propia", (.1, .1, .9, .1, .9, .1, .1, .1), 10, 1, {"2": ["t0"], "4": ["t1"]},
            text_evidence={"t0": {"choice": "nivel_2", "score": .9}, "t1": {"choice": "nivel_4", "score": .9}},
        )
        self.alerts.register_alert.side_effect = [PersistenceUnavailable(), None]
        with self.assertRaises(PersistenceUnavailable):
            self.resume()
        self.resume()
        self.analyzer.evaluate.assert_called_once()
        first, retry = [call.kwargs for call in self.alerts.register_alert.call_args_list]
        self.assertEqual(first["alerta_id"], retry["alerta_id"])
        self.assertEqual(first["nivel_severidad"], 3)
        self.assertEqual(first["analisis"], retry["analisis"])
        self.assertEqual(len(retry["analisis"]["evidencias"]), 2)
