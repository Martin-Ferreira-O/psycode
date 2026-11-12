"""Una decisión conjunta no se repite al recuperar su entrega."""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

from django.test import SimpleTestCase
from backend.apps.analysis.domain import Fragment, JevDecision
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
        self.analyzer.evaluate.return_value = JevDecision("simulated", "afirmacion_propia", (.1, .9, .1, .1, .1, .1, .1, .1), 10, 1)
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
        self.assertEqual(len(result.signals), 1)
        self.assertEqual(self.alerts.register_alert.call_count, 1)
        current = self.analyzer.evaluate.call_args.args[0]
        self.assertIn("¿Cómo estás?", current["text"])
        self.assertIn('"role": "professional"', current["text"])
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

    def test_synthetic_test_roles_do_not_leak_into_clinical_blocks(self):
        from dataclasses import replace
        self.checkpoint.data["roles"] = {}
        clinical, _ = self.resume()
        self.assertFalse(clinical.signals)
        self.alerts.register_alert.assert_not_called()
        self.checkpoint = Checkpoint()
        self.checkpoint.data["roles"] = {}
        self.fragment = replace(self.fragment, audio_test=True)
        synthetic, context = self.resume()
        self.assertEqual(len(synthetic.signals), 1)
        self.assertEqual(len(context["test_alerts"]), 1)
