from datetime import timedelta
from hashlib import sha256
from io import StringIO
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
import httpx
from pymongo.errors import AutoReconnect

from backend.apps.alerts.repositories import AlertsRepository
from backend.apps.alerts.tests.test_persistence import FakeDatabase
from backend.apps.analysis.providers.settings import Settings
from backend.apps.analysis.tests.test_integration import answer
from backend.apps.notifications.domain import AttemptResult
from backend.apps.operational.models import NotificationMode
from backend.config.composition import fragment_job_processor

from .models import CaptureSession, FragmentJob
from .test_ingestion import IngestionFixtures, wav_bytes
from .tests import NOW


class FragmentRecoveryTests(IngestionFixtures, TestCase):
    def setUp(self):
        super().setUp()
        CaptureSession.objects.filter(pk=self.session.session_id).update(capture_chunk_config={})
        self.db = FakeDatabase()
        self.store = AlertsRepository(self.db)
        self.store.ensure_schema()
        self.speech_calls = []
        self.jev_calls = []
        self.speech_failure = None
        self.jev_statuses = []
        self.speaker = "S1"
        self.two_utterances = False
        self.primary = Mock()
        self.primary.send.return_value = AttemptResult("email", False, 10, "NOTIFICATION_REJECTED")
        self.backup = Mock()
        self.backup.send.return_value = AttemptResult("email", True, 10)
        self.now = timezone.now()
        self.override = override_settings(CAPTURE_FRAGMENT_ROOT=self.root)
        self.override.enable()
        self.addCleanup(self.override.disable)

    def queue(self, number=0):
        job_id = self.receive(content=wav_bytes(b"\x00\x00" * 64000), number=number,
                              captured_at=NOW + timedelta(seconds=10 + number),
                              now=NOW + timedelta(seconds=20 + number))[0].job_id
        FragmentJob.objects.filter(pk=job_id).update(checkpoint={"analysis_unit": "utterance"})
        return job_id

    def speech(self, req):
        self.speech_calls.append((req.method, req.url.path))
        if req.method == "POST":
            if self.speech_failure == "uncertain":
                self.speech_failure = None
                raise httpx.ReadTimeout("synthetic timeout")
            return httpx.Response(201, json={"id": "batch-id"})
        if req.url.path == "/v2/jobs/":
            session = self.session.session_id
            ref = sha256(f"{session}:0".encode()).hexdigest()
            return httpx.Response(200, json={"jobs": [
                {"id": "batch-id", "status": "done", "config": {"tracking": {"reference": ref}}},
            ]})
        if req.method == "DELETE":
            return httpx.Response(200)
        if req.url.path.endswith("/transcript"):
            words = [{"type": "word", "start_time": 0, "end_time": 1,
                      "alternatives": [{"content": "Ojalá no despertar", "speaker": self.speaker}]}]
            if self.two_utterances:
                words.append({"type": "word", "start_time": 2, "end_time": 3,
                              "alternatives": [{"content": "Ojalá no despertar", "speaker": "S2"}]})
            return httpx.Response(200, json={"results": words})
        if self.speech_failure == "poll":
            return httpx.Response(503)
        return httpx.Response(200, json={"job": {"status": "done"}})

    def jev(self, req):
        self.jev_calls.append(json.loads(req.content)["state"])
        return httpx.Response(self.jev_statuses.pop(0) if self.jev_statuses else 200, json=answer(1))

    def worker(self):
        speech = httpx.Client(transport=httpx.MockTransport(self.speech))
        jev = httpx.Client(transport=httpx.MockTransport(self.jev))
        self.addCleanup(speech.close)
        self.addCleanup(jev.close)
        worker = fragment_job_processor(
            settings=Settings(speechmatics_key="fake", jev_key="fake", external_enabled=True),
            directory=self.root / "analysis", speechmatics_http=speech, jev_http=jev, alert_store=self.store,
            roles_provider=lambda fragment: {
                f"batch-{fragment.sequence}-{speaker}": "patient" for speaker in ("S1", "S2", "S7")
            },
        )
        worker.analysis.transcriptor.batch.sleep = worker.analysis.analyzer.sleep = lambda _: None
        notifier = worker.analysis.alerts.notifier
        notifier.enabled = True
        notifier.email_client = self.primary
        notifier.backup_email_client = self.backup
        notifier.recipient_resolver = Mock()
        notifier.recipient_resolver.resolve.return_value = SimpleNamespace(
            emails=["primary@example.test"], reason=None, mode=NotificationMode.ACTIVE_SUPERVISORS,
            backup_enabled=True, backup_email="backup@example.test",
        )
        return worker

    def test_recovers_mongo_write_and_preserves_dates_context_and_notifications(self):
        job_id = self.queue()
        collection = self.db["alerts"]
        insert = collection.insert_one

        def accepted_before_disconnect(document):
            insert(document)
            raise AutoReconnect()

        collection.insert_one = accepted_before_disconnect
        self.assertEqual(self.worker().process_next(now=self.now), FragmentJob.State.PENDING)
        stored = collection.docs[0].copy()
        job = FragmentJob.objects.get(pk=job_id)
        self.assertIn("result", job.checkpoint)
        self.assertTrue(self.blobs())
        self.primary.send.assert_not_called()

        collection.insert_one = insert
        self.assertIsNone(self.worker().process_next(now=job.retry_at - timedelta(seconds=1)))
        self.assertEqual(self.worker().process_next(now=job.retry_at), FragmentJob.State.COMPLETED)
        self.assertEqual(collection.docs, [stored])
        self.assertEqual(len(self.speech_calls), 4)
        self.assertEqual(len(self.jev_calls), 1)
        self.assertEqual(stored["descripcion"], "Ojalá no despertar")
        session = CaptureSession.objects.get(pk=self.session.session_id)
        self.assertEqual(stored["fecha_hora"], session.actual_start)
        self.assertGreater(stored["trazabilidad"]["registrada_en"], stored["fecha_hora"])
        self.primary.send.assert_called_once()
        self.backup.send.assert_called_once()

        service = self.worker().analysis.alerts
        service.record_evaluation(stored["alerta_id"], "correcta", str(uuid4()), "Supervisor")
        events = self.db["audit_events"].docs
        for action in ("alerts.register", "notifications.result", "alerts.evaluate"):
            self.assertEqual(sum(event["action"] == action for event in events), 1)
        self.assertEqual([event["notification"]["phase"] for event in events
                          if event["action"] == "notifications.send"], ["principal", "respaldo"])

        self.speaker = "S7"
        self.queue(1)
        self.assertEqual(self.worker().process_next(now=self.now), FragmentJob.State.COMPLETED)
        self.assertEqual(self.jev_calls[-1]["history"], [self.jev_calls[0]["current"]])
        self.assertEqual(self.jev_calls[-1]["current"]["role"], "patient")

    def test_polls_known_batch_after_restart_and_does_not_post_again(self):
        self.speech_failure = "poll"
        job_id = self.queue()
        self.assertEqual(self.worker().process_next(now=self.now), FragmentJob.State.PENDING)
        job = FragmentJob.objects.get(pk=job_id)
        self.assertEqual(job.checkpoint["speechmatics"]["job_id"], "batch-id")
        self.assertFalse(any(method == "DELETE" for method, _ in self.speech_calls))
        self.speech_failure = None
        self.assertEqual(self.worker().process_next(now=job.retry_at), FragmentJob.State.COMPLETED)
        self.assertEqual(sum(method == "POST" for method, _ in self.speech_calls), 1)

    def test_reconciles_uncertain_batch_before_resending(self):
        self.speech_failure = "uncertain"
        job_id = self.queue()
        self.assertEqual(self.worker().process_next(now=self.now), FragmentJob.State.PENDING)
        job = FragmentJob.objects.get(pk=job_id)
        self.assertEqual(job.last_error_code, "SPEECHMATICS_UNCERTAIN")
        self.assertEqual(self.worker().process_next(now=job.retry_at), FragmentJob.State.COMPLETED)
        self.assertIn(("GET", "/v2/jobs/"), self.speech_calls)
        self.assertEqual(sum(method == "POST" for method, _ in self.speech_calls), 1)

    def test_jev_retry_continues_from_last_confirmed_utterance(self):
        self.two_utterances = True
        self.jev_statuses = [200, 429, 429, 429]
        job_id = self.queue()
        self.assertEqual(self.worker().process_next(now=self.now), FragmentJob.State.PENDING)
        job = FragmentJob.objects.get(pk=job_id)
        self.assertEqual(job.checkpoint["next_utterance"], 1)
        self.assertEqual(self.worker().process_next(now=job.retry_at), FragmentJob.State.COMPLETED)
        self.assertEqual(len(self.speech_calls), 4)
        self.assertEqual([state["current"]["start"] for state in self.jev_calls], [0, 2, 2, 2, 2])

    def test_ambiguous_jev_requires_review_and_preserves_audio(self):
        self.jev_statuses = [503]
        job_id = self.queue()
        self.assertEqual(self.worker().process_next(now=self.now), FragmentJob.State.REVIEW)
        self.assertIsNone(self.worker().process_next(now=self.now + timedelta(hours=3)))
        self.assertEqual(len(self.jev_calls), 1)
        self.assertTrue(self.blobs())
        CaptureSession.objects.filter(pk=self.session.session_id).update(
            actual_end=timezone.now() - timedelta(hours=3), final_sequence=0,
        )
        report = StringIO()
        call_command("process_fragment_jobs", "--report-processing", stdout=report)
        self.assertIn(f"trabajo={job_id}", report.getvalue())
        self.assertIn("JEV_SUBMISSION_UNCERTAIN", report.getvalue())
        self.assertIn("RETRASO", report.getvalue())
        session = self.service.inspection(3, self.session.session_id, now=timezone.now())
        self.assertEqual(session["processing"], "intervention_required")
        self.assertEqual(session["job_counts"]["revision"], 1)

    def test_late_fragment_after_capture_end_resumes_context_and_reports_elapsed_time(self):
        self.queue()
        sid = self.session.session_id
        ended = NOW + timedelta(seconds=25)
        self.service.interrupted(3, sid, now=ended)
        self.service.confirm_capture_ended(
            3, sid, ended_at=ended, last_sequence=1, reason_code="AGENT_INTERRUPTED",
            now=ended + timedelta(seconds=1),
        )
        with patch("backend.apps.capture.processing.timezone.now", return_value=ended + timedelta(minutes=30)):
            self.assertEqual(self.worker().process_next(), FragmentJob.State.COMPLETED)

        report = StringIO()
        with patch("backend.apps.capture.processing.timezone.now", return_value=ended + timedelta(minutes=75)):
            call_command("process_fragment_jobs", "--report-processing", stdout=report)
        self.assertIn("PENDIENTE_MAS_DE_1_HORA", report.getvalue())

        late, _ = self.receive(
            content=wav_bytes(b"\x00\x00" * 64000), number=1,
            captured_at=NOW + timedelta(seconds=11), now=ended + timedelta(minutes=80),
        )
        FragmentJob.objects.filter(pk=late.job_id).update(checkpoint={"analysis_unit": "utterance"})
        self.speaker = "S7"
        with patch("backend.apps.capture.processing.timezone.now", return_value=ended + timedelta(minutes=90)):
            self.assertEqual(self.worker().process_next(), FragmentJob.State.COMPLETED)
        self.assertEqual(self.jev_calls[-1]["history"], [self.jev_calls[0]["current"]])
        report = StringIO()
        call_command("process_fragment_jobs", "--report-processing", stdout=report)
        self.assertIn(f"OBJETIVO_1_A_2_HORAS sesión={sid} segundos=5400", report.getvalue())


    def test_retention_keeps_excerpt_evaluation_and_web_detail_after_purging_processing(self):
        from copy import deepcopy
        from rest_framework.test import APIClient
        from backend.apps.accounts.models import User
        from .retention import cleanup
        self.queue()
        worker = self.worker()
        self.assertEqual(worker.process_next(now=self.now), FragmentJob.State.COMPLETED)
        alert = self.db['alerts'].docs[0]
        user = User.objects.create_user(username='review-retention', email='review@retention.test', password='Synthetic-2026!')
        worker.analysis.alerts.record_evaluation(alert['alerta_id'], 'correcta', str(user.pk), user.username)
        retained = deepcopy(self.db['alerts'].docs)
        events = deepcopy(self.db['audit_events'].docs)
        CaptureSession.objects.update(actual_end=self.now, final_sequence=0, state='completada')
        run = cleanup(self.storage, now=self.now + timedelta(hours=25))
        self.assertEqual(run.removed, 1)
        self.assertEqual(FragmentJob.objects.get().checkpoint, {})
        self.assertEqual(self.db['alerts'].docs, retained)
        self.assertEqual(self.db['audit_events'].docs, events)
        api = APIClient()
        api.force_authenticate(user=user)
        with patch('backend.apps.alerts.views.get_service', return_value=worker.analysis.alerts):
            detail = api.get('/api/v1/alerts/' + alert['alerta_id'])
            evaluation = api.get('/api/v1/alerts/' + alert['alerta_id'] + '/evaluacion')
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertIn('Ojalá no despertar', str(detail.data))
        self.assertEqual(evaluation.status_code, 200, evaluation.data)
        self.assertIn('correcta', str(evaluation.data))
