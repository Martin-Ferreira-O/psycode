from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock
from uuid import uuid4

from backend.apps.analysis.domain import AnalysisState, Fragment, JevDecision, Transcription, Word
from backend.apps.analysis.services import AnalysisService


class BlockAudioTestRolesTests(TestCase):
    def test_alerts_group_repeated_plain_text_with_or_without_speaker_labels(self):
        for audio_test, speaker, roles in (
            (True, "S1", {}),
            (False, "S1", {}),
            (True, None, {}),
            (True, "S1", {"S1": "professional"}),
        ):
            with self.subTest(audio_test=audio_test, speaker=speaker, roles=roles):
                transcriber, analyzer, alerts = Mock(), Mock(), Mock()
                transcriber.transcribe.return_value = Transcription("Ojalá no despertar.", (
                    Word("Ojalá no despertar.", 0, 1, speaker),
                    Word("Ojalá no despertar.", 2, 3, speaker),
                ), "deleted")
                analyzer.evaluate.return_value = JevDecision(
                    "simulated", "incierto", (.1, .9, .1, .1, .1, .1, .1, .1), 1, 1,
                    text_evidence={key: {"choice": "nivel_1", "score": .9} for key in ("t0", "t1")},
                )
                service = AnalysisService(transcriber, analyzer, Mock(), alerts, Mock())
                fragment = Fragment(str(uuid4()), 0, "box-3", datetime.now(timezone.utc),
                                    Path("synthetic.wav"), end=64000, analysis_unit="fragment")
                result = service.process(replace(fragment, audio_test=audio_test), roles=roles)
                self.assertEqual(result.state, AnalysisState.SIGNAL)
                self.assertEqual(len(result.signals), 2)
                analyzer.evaluate.assert_called_once()
                alerts.register_alert.assert_called_once()
                current = analyzer.evaluate.call_args.args[0]
                self.assertEqual(current["text"], "[t0] Ojalá no despertar.\n[t1] Ojalá no despertar.")

    def test_overlap_keeps_the_statement_that_extends_into_new_audio(self):
        transcriber, analyzer, alerts = Mock(), Mock(), Mock()
        transcriber.transcribe.return_value = Transcription("", (
            Word("Ojalá no despertar.", .2, .5, None),
            Word("He pensado en quitarme la vida.", .6, 1.2, None),
        ), "deleted")
        analyzer.evaluate.return_value = JevDecision(
            "simulated", "incierto", (.1,) * 8, 1, 1,
            text_evidence={"t0": {"choice": "nivel_1", "score": .9},
                           "t1": {"choice": "nivel_2", "score": .9}},
        )
        fragment = Fragment(str(uuid4()), 0, "box-3", datetime.now(timezone.utc), Path("synthetic.wav"),
                            end=32000, new_audio_start_sample=16000)
        result = AnalysisService(transcriber, analyzer, Mock(), alerts, Mock()).process(fragment)
        signal, = result.signals
        self.assertEqual((signal.start, signal.end, signal.matrix_level), (.6, 1.2, 2))
