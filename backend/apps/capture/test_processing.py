from datetime import timedelta
from uuid import uuid4

from django.test import TestCase

from backend.apps.analysis.domain import AnalysisResult, AnalysisState
from .models import FragmentJob
from .processing import FragmentJobProcessor
from .test_ingestion import IngestionFixtures
from .tests import NOW


class FakeAnalysis:
    def __init__(self, state=AnalysisState.NO_SIGNAL, error_codes=(), error=None):
        self.state = state
        self.error_codes = error_codes
        self.error = error
        self.calls = []
        self.closed = []

    def process(self, fragment, *, roles=None):
        self.calls.append((fragment, roles or {}))
        if self.error is not None:
            raise self.error
        return AnalysisResult(
            fragment.session_id,
            fragment.sequence,
            self.state,
            error_codes=self.error_codes,
        )

    def close_session(self, session_id):
        self.closed.append(session_id)


class FakeAudit:
    def __init__(self):
        self.failures = []
        self.recoveries = []

    def failure(self, code, *, alerta_id=None, sesion_id=None, sequence=None):
        self.failures.append((code, sesion_id, sequence))

    def recovery(self, *, sesion_id=None, sequence=None):
        self.recoveries.append((sesion_id, sequence))


class FragmentJobProcessorTests(IngestionFixtures, TestCase):
    def processor(
        self,
        *,
        state=AnalysisState.NO_SIGNAL,
        error_codes=(),
        error=None,
        max_attempts=3,
        stuck_after=timedelta(minutes=5),
    ):
        analysis = FakeAnalysis(state, error_codes, error)
        audit = FakeAudit()
        processor = FragmentJobProcessor(
            self.storage,
            analysis,
            roles_provider=lambda fragment: {
                f"batch-{fragment.sequence}-S1": "patient"
            },
            audit=audit,
            max_attempts=max_attempts,
            stuck_after=stuck_after,
        )
        return processor, analysis, audit

    def test_signal_completes_job_with_risk_and_deletes_fragment(self):
        self.receive()
        processor, analysis, _ = self.processor(state=AnalysisState.SIGNAL)

        state = processor.process_next(now=NOW + timedelta(seconds=21))

        job = FragmentJob.objects.get()
        self.assertEqual(state, FragmentJob.State.COMPLETED)
        self.assertEqual(job.state, FragmentJob.State.COMPLETED)
        self.assertEqual(job.result, FragmentJob.Result.RISK_DETECTED)
        self.assertEqual(job.attempts, 1)
        self.assertIsNotNone(job.finished_at)
        self.assertEqual(job.last_error_code, "")
        self.assertFalse(self.blobs())
        self.assertEqual(len(analysis.calls), 1)
        self.assertEqual(
            analysis.calls[0][1],
            {"batch-0-S1": "patient"},
        )

    def test_no_risk_completes_without_alert_result(self):
        self.receive()
        processor, analysis, _ = self.processor(state=AnalysisState.NO_SIGNAL)

        state = processor.process_next(now=NOW + timedelta(seconds=21))

        job = FragmentJob.objects.get()
        self.assertEqual(state, FragmentJob.State.COMPLETED)
        self.assertEqual(job.result, FragmentJob.Result.NO_RISK_DETECTED)
        self.assertFalse(self.blobs())
        self.assertEqual(len(analysis.calls), 1)

    def test_analytical_indeterminate_is_completed_not_failed(self):
        self.receive()
        processor, _, audit = self.processor(
            state=AnalysisState.INDETERMINATE,
            error_codes=("CONTEXT_NOT_EVALUABLE",),
        )

        state = processor.process_next(now=NOW + timedelta(seconds=21))

        job = FragmentJob.objects.get()
        self.assertEqual(state, FragmentJob.State.COMPLETED)
        self.assertEqual(job.state, FragmentJob.State.COMPLETED)
        self.assertEqual(job.result, FragmentJob.Result.INDETERMINATE)
        self.assertEqual(job.last_error_code, "")
        self.assertEqual(audit.failures, [])
        self.assertFalse(self.blobs())

    def test_technical_indeterminate_marks_job_failed(self):
        self.receive()
        processor, _, audit = self.processor(
            state=AnalysisState.INDETERMINATE,
            error_codes=("JEV_FAILED",),
        )

        state = processor.process_next(now=NOW + timedelta(seconds=21))

        job = FragmentJob.objects.get()
        self.assertEqual(state, FragmentJob.State.FAILED)
        self.assertEqual(job.state, FragmentJob.State.FAILED)
        self.assertEqual(job.result, "")
        self.assertEqual(job.last_error_code, "JEV_FAILED")
        self.assertEqual(audit.failures, [])
        self.assertFalse(self.blobs())

    def test_local_processing_exception_marks_job_failed(self):
        self.receive()
        processor, _, audit = self.processor(error=RuntimeError("private"))

        state = processor.process_next(now=NOW + timedelta(seconds=21))

        job = FragmentJob.objects.get()
        self.assertEqual(state, FragmentJob.State.FAILED)
        self.assertEqual(job.last_error_code, "FLOW_INTERRUPTED")
        self.assertEqual(audit.failures, [])
        self.assertFalse(self.blobs())

    def test_stuck_job_is_recovered_before_retry_limit(self):
        self.receive()
        job = FragmentJob.objects.get()
        job.state = FragmentJob.State.PROCESSING
        job.attempts = 1
        job.processing_started_at = NOW
        job.processing_token = uuid4()
        job.save(
            update_fields=[
                "state",
                "attempts",
                "processing_started_at",
                "processing_token",
            ]
        )

        processor, _, audit = self.processor()

        recovered, failed = processor.recover_stuck(
            now=NOW + timedelta(minutes=6)
        )

        job.refresh_from_db()
        self.assertEqual((recovered, failed), (1, 0))
        self.assertEqual(job.state, FragmentJob.State.PENDING)
        self.assertIsNone(job.processing_started_at)
        self.assertIsNone(job.processing_token)
        self.assertEqual(job.last_error_code, "FLOW_INTERRUPTED")
        self.assertEqual(
            audit.recoveries,
            [(str(self.session.session_id), 0)],
        )
        self.assertEqual(len(self.blobs()), 1)

    def test_stuck_job_fails_after_maximum_attempts(self):
        self.receive()
        job = FragmentJob.objects.get()
        job.state = FragmentJob.State.PROCESSING
        job.attempts = 3
        job.processing_started_at = NOW
        job.processing_token = uuid4()
        job.save(
            update_fields=[
                "state",
                "attempts",
                "processing_started_at",
                "processing_token",
            ]
        )

        processor, _, audit = self.processor(max_attempts=3)

        recovered, failed = processor.recover_stuck(
            now=NOW + timedelta(minutes=6)
        )

        job.refresh_from_db()
        self.assertEqual((recovered, failed), (0, 1))
        self.assertEqual(job.state, FragmentJob.State.FAILED)
        self.assertEqual(job.last_error_code, "FLOW_INTERRUPTED")
        self.assertIsNotNone(job.finished_at)
        self.assertEqual(
            audit.failures,
            [("FLOW_INTERRUPTED", str(self.session.session_id), 0)],
        )
        self.assertFalse(self.blobs())

    def test_later_sequence_waits_while_previous_job_is_not_completed(self):
        self.receive()
        self.receive(
            number=1,
            captured_at=NOW + timedelta(seconds=11),
            now=NOW + timedelta(seconds=21),
        )

        first = FragmentJob.objects.get(sequence__number=0)
        second = FragmentJob.objects.get(sequence__number=1)

        first.state = FragmentJob.State.PROCESSING
        first.attempts = 1
        first.processing_started_at = NOW + timedelta(seconds=20)
        first.processing_token = uuid4()
        first.save(
            update_fields=[
                "state",
                "attempts",
                "processing_started_at",
                "processing_token",
            ]
        )

        processor, analysis, _ = self.processor()

        result = processor.process_next(now=NOW + timedelta(seconds=22))

        second.refresh_from_db()
        self.assertIsNone(result)
        self.assertEqual(second.state, FragmentJob.State.PENDING)
        self.assertEqual(analysis.calls, [])

    def test_completed_job_is_not_processed_twice(self):
        self.receive()
        processor, analysis, _ = self.processor()

        first = processor.process_next(now=NOW + timedelta(seconds=21))
        second = processor.process_next(now=NOW + timedelta(seconds=22))

        self.assertEqual(first, FragmentJob.State.COMPLETED)
        self.assertIsNone(second)
        self.assertEqual(len(analysis.calls), 1)

    def test_stuck_job_is_not_recovered_while_fragment_is_leased(self):
        self.receive()
        job = FragmentJob.objects.get()
        job.state = FragmentJob.State.PROCESSING
        job.attempts = 1
        job.processing_started_at = NOW
        job.processing_token = uuid4()
        job.save(
            update_fields=[
                "state",
                "attempts",
                "processing_started_at",
                "processing_token",
            ]
        )

        processor, _, audit = self.processor()

        with self.storage.lease(job.storage_key):
            recovered, failed = processor.recover_stuck(
                now=NOW + timedelta(minutes=6)
            )

        job.refresh_from_db()

        self.assertEqual((recovered, failed), (0, 0))
        self.assertEqual(job.state, FragmentJob.State.PROCESSING)
        self.assertIsNotNone(job.processing_token)
        self.assertEqual(audit.recoveries, [])
        self.assertEqual(audit.failures, [])
        self.assertEqual(len(self.blobs()), 1)
