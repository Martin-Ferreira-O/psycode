"""Regresión de unidad operativa: una hora produce seis análisis, o uno completo."""
from datetime import timedelta
from io import StringIO
from unittest.mock import Mock

from django.core.management import call_command
from django.test import TestCase
from backend.apps.analysis.domain import Transcription, Word, JevDecision
from backend.apps.analysis.services import AnalysisService
from .models import CaptureSession, FragmentJob
from .processing import FragmentJobProcessor, QueueFragmentLedger
from .test_ingestion import IngestionFixtures, wav_bytes
from .tests import NOW


class BlockAnalysisPipelineTests(IngestionFixtures, TestCase):
    def exercise(self, seconds):
        CaptureSession.objects.filter(pk=self.session.session_id).update(
            capture_chunk_config={"audio_chunk_mode": "session" if seconds == 3600 else "fixed",
                                  "audio_chunk_duration": seconds, "audio_chunk_overlap": 0,
                                  "analysis_unit": "fragment"},
            capture_chunk_negotiated=True)
        count = 3600 // seconds
        wav = wav_bytes(bytes(seconds * 32000))
        for number in range(count):
            start, end = number * seconds * 16000, (number + 1) * seconds * 16000
            self.receive(content=wav, number=number, captured_at=NOW + timedelta(seconds=number * seconds),
                         now=NOW + timedelta(seconds=(number + 1) * seconds), temporal={
                             "session_start_sample": start, "session_end_sample": end,
                             "new_audio_start_sample": start, "sample_rate": 16000,
                             "chunk_samples": seconds * 16000, "overlap_samples": 0})
        transcriber, analyzer, alerts = Mock(), Mock(), Mock()
        words = tuple(Word("Texto sintético neutral.", offset, offset + 1, "S1") for offset in range(0, seconds, 15))
        transcriber.transcribe.side_effect = lambda fragment, **kw: self.transcribe(words, **kw)
        analyzer.evaluate.return_value = JevDecision("simulated", "incierto", (.1,) * 8, 10, 1)
        service = AnalysisService(transcriber, analyzer, QueueFragmentLedger(), alerts, Mock())
        processor = FragmentJobProcessor(self.storage, service)
        for _ in range(count):
            processor.process_next(now=NOW + timedelta(hours=2))
        self.assertEqual(transcriber.transcribe.call_count, count)
        self.assertEqual(analyzer.evaluate.call_count, count)
        self.assertEqual(FragmentJob.objects.filter(state=FragmentJob.State.COMPLETED).count(), count)
        for job in FragmentJob.objects.all():
            self.assertEqual(job.checkpoint["analysis_unit"], "fragment")
            self.assertEqual(len(job.checkpoint["block_result"]["decisions"]), 1)
        for call in analyzer.evaluate.call_args_list:
            turns = call.args[0]["turns"]
            self.assertEqual(len(turns), len(words))
            self.assertTrue(all(turn["text"] == "Texto sintético neutral." for turn in turns))
        processor.process_next(now=NOW + timedelta(hours=2))
        self.assertEqual(analyzer.evaluate.call_count, count)
        alerts.register_alert.assert_not_called()

    @staticmethod
    def transcribe(words, checkpoint, prepare):
        checkpoint.data["speechmatics"] = {"state": "deleted"}
        checkpoint.data["utterances"] = prepare([{
            "text": w.text, "start": w.start, "end": w.end, "speaker": w.speaker,
        } for w in words])
        checkpoint.save()
        return Transcription(" ".join(w.text for w in words), words, "deleted")

    def test_hour_with_ten_minute_blocks_has_six_jev_analyses(self):
        self.exercise(600)

    def test_entire_hour_has_one_jev_analysis(self):
        self.exercise(3600)

    def test_context_limit_requires_review_and_preserves_audio(self):
        from backend.apps.analysis.errors import JevContextLimit
        self.receive()
        self.receive(number=1, captured_at=NOW + timedelta(seconds=11))
        transcriber, analyzer = Mock(), Mock()
        words = (Word("Texto sintético neutral.", 0, 1, "S1"),)
        transcriber.transcribe.side_effect = lambda fragment, **kw: self.transcribe(words, **kw)
        analyzer.evaluate.side_effect = [
            JevContextLimit("JEV_CONTEXT_LIMIT"),
            JevDecision("simulated", "incierto", (.1,) * 8, 10, 1),
            JevDecision("simulated", "incierto", (.1,) * 8, 10, 1),
        ]
        processor = FragmentJobProcessor(self.storage, AnalysisService(
            transcriber, analyzer, QueueFragmentLedger(), Mock(), Mock()))
        processor.process_next(now=NOW + timedelta(hours=2))
        job = FragmentJob.objects.get(sequence__number=0)
        self.assertEqual(job.state, FragmentJob.State.REVIEW)
        self.assertEqual(job.last_error_code, "JEV_CONTEXT_LIMIT")
        self.assertTrue((self.root / job.storage_key).exists())
        self.assertEqual(processor.process_next(now=NOW + timedelta(hours=2)), FragmentJob.State.COMPLETED)
        self.assertEqual(analyzer.evaluate.call_count, 2)
        self.assertEqual(FragmentJob.objects.get(sequence__number=1).state, FragmentJob.State.COMPLETED)

        # Compatibilidad con trabajos en revisión guardados por el worker anterior.
        request_id = analyzer.evaluate.call_args_list[0].kwargs["request_id"]
        job.checkpoint.pop("jev_retry_request_id")
        job.checkpoint["jev_pending"] = {"analysis_unit": "fragment", "request_id": request_id}
        job.save(update_fields=["checkpoint"])
        call_command("process_fragment_jobs", "--resume-job", str(job.pk), stdout=StringIO())
        self.assertEqual(processor.process_next(now=NOW + timedelta(hours=2)), FragmentJob.State.COMPLETED)
        self.assertEqual(analyzer.evaluate.call_args.kwargs["request_id"], request_id)
        self.assertEqual(transcriber.transcribe.call_count, 2)
