"""Compatibilidad del diagnóstico sintético sin inferir roles clínicos."""
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock
from uuid import uuid4

from backend.apps.analysis.domain import AnalysisState, Fragment, JevDecision, Transcription, Word
from backend.apps.analysis.services import AnalysisService


class BlockAudioTestRolesTests(TestCase):
    def test_fictional_patient_is_scoped_to_assigned_synthetic_voices(self):
        for audio_test, speaker, roles, expected in (
            (True, "S1", {}, AnalysisState.SIGNAL),
            (False, "S1", {}, AnalysisState.INDETERMINATE),
            (True, None, {}, AnalysisState.INDETERMINATE),
            (True, "S1", {"S1": "professional"}, AnalysisState.INDETERMINATE),
        ):
            with self.subTest(audio_test=audio_test, speaker=speaker, roles=roles):
                transcriber, analyzer, alerts = Mock(), Mock(), Mock()
                transcriber.transcribe.return_value = Transcription("Ojalá no despertar.", (
                    Word("Ojalá no despertar.", 0, 1, speaker),
                    Word("Ojalá no despertar.", 2, 3, speaker),
                ), "deleted")
                analyzer.evaluate.return_value = JevDecision(
                    "simulated", "afirmacion_propia", (.1, .9, .1, .1, .1, .1, .1, .1), 1, 1)
                service = AnalysisService(transcriber, analyzer, Mock(), alerts, Mock())
                fragment = Fragment(str(uuid4()), 0, "box-3", datetime.now(timezone.utc),
                                    Path("synthetic.wav"), end=64000, analysis_unit="fragment")
                result = service.process(replace(fragment, audio_test=audio_test), roles=roles)
                self.assertEqual(result.state, expected)
                analyzer.evaluate.assert_called_once()
                self.assertEqual(len(result.decisions), 1)
                self.assertEqual(alerts.register_alert.call_count, int(expected == AnalysisState.SIGNAL))
                current = analyzer.evaluate.call_args.args[0]
                self.assertEqual(len(current["turns"]), 2)
                expected_roles = {"voz1": roles.get("S1", "patient" if audio_test else "unknown")} if speaker else {}
                self.assertEqual(current["speaker_roles"], expected_roles)
