from dataclasses import replace
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from .models import AgentCommand, CaptureEvent, CaptureSession
from .services import CaptureSessionService
from .test_ingestion import IngestionFixtures
from .tests import CaptureFixtures, NOW


class OfflineSessionContinuityTests(CaptureFixtures, TestCase):
    def test_long_disconnect_accepts_authorized_audio_and_historical_stop(self):
        session = self.active()
        reconnected = NOW + timedelta(days=3)
        stop, = self.service.commands(3, now=reconnected)
        self.assertEqual(stop.kind, "detencion")
        result = self.service.acknowledge(
            3, stop.command_id, occurred_at=self.authorization.termino,
            last_sequence=0, now=reconnected,
        )
        self.assertEqual(result.actual_end, self.authorization.termino)
        self.assertTrue(self.accept(session, received=3 * 86400 + 1))
        self.assertEqual(CaptureSession.objects.get().state, "completada")

    def test_delayed_start_after_window_records_execution_without_reactivating_capture(self):
        self.create()
        start, = self.service.commands(3, now=NOW)
        result = self.service.acknowledge(3, start.command_id, occurred_at=NOW,
                                          now=NOW + timedelta(days=2))
        self.assertEqual(result.actual_start, NOW)
        self.assertEqual(result.state, "finalizando")
        self.assertIsNone(result.actual_end)
        self.assertTrue(self.accept(result, received=2 * 86400 + 1))
        self.assert_code("SEQUENCE_OUTSIDE_CAPTURE_WINDOW", self.accept, result,
                         number=1, seconds=3601, received=2 * 86400 + 2)

    def test_next_authorization_starts_while_previous_reception_is_pending(self):
        original = self.active()
        self.ack_stop(self.stop(), last_sequence=1)
        next_session = self.service.apply_authorization(self.authorization, now=NOW + timedelta(seconds=40))
        self.assertNotEqual(original.session_id, next_session.session_id)
        self.assertEqual(CaptureSession.objects.get(pk=original.session_id).state, "finalizando")
        self.assertTrue(self.accept(original, received=6 * 86400))
        self.assertEqual(CaptureSession.objects.get(pk=next_session.session_id).state, "iniciada")

    def test_reception_deadline_is_recoverable_and_never_extends_capture(self):
        session = self.active()
        self.ack_stop(self.stop(), last_sequence=1)
        deadline = NOW + timedelta(seconds=30, days=7)
        self.assertTrue(self.service.accept_sequence(3, session.session_id, 0,
                        NOW + timedelta(seconds=10), now=deadline - timedelta(seconds=1)))
        self.assert_code("RECEPTION_INTERVENTION_REQUIRED", self.service.accept_sequence,
                         3, session.session_id, 1, NOW + timedelta(seconds=20), now=deadline)
        stored = CaptureSession.objects.get()
        self.assertEqual(stored.state, "finalizando")
        self.assertIsNone(stored.closed_at)
        self.assertEqual(stored.next_sequence, 1)
        snapshot = self.service.inspection(3, session.session_id, now=deadline)
        self.assertEqual(snapshot["capture"], "finished")
        self.assertEqual(snapshot["reception"], "intervention_required")
        self.assertEqual(snapshot["backlog_alert"], "critical")
        self.service.resume_reception(3, session.session_id, now=deadline + timedelta(days=1))
        self.assertTrue(self.service.accept_sequence(3, session.session_id, 1,
                        NOW + timedelta(seconds=20), now=deadline + timedelta(days=1, seconds=1)))
        self.assertEqual(CaptureSession.objects.get().state, "completada")
        self.assertEqual(CaptureEvent.objects.filter(action="capture.reception.resumed").count(), 1)

    def test_unknown_final_sequence_releases_capture_without_fabricating_command_ack(self):
        session = self.active()
        ended = NOW + timedelta(seconds=20)
        result = self.service.confirm_capture_ended(3, session.session_id,
            ended_at=ended, reason_code="RECOVERY_STOPPED", now=ended + timedelta(seconds=1))
        self.assertEqual(result.state, "finalizando")
        self.assertIsNone(result.final_sequence)
        stop = AgentCommand.objects.get(session_id=session.session_id, kind="detencion")
        self.assertIsNone(stop.succeeded)
        count = CaptureEvent.objects.count()
        self.service.confirm_capture_ended(3, session.session_id,
            ended_at=ended, reason_code="RECOVERY_STOPPED", now=ended + timedelta(seconds=2))
        self.assertEqual(CaptureEvent.objects.count(), count)
        next_authorization = replace(self.authorization, inicio=NOW + timedelta(seconds=30),
                                     termino=NOW + timedelta(hours=2))
        resumed = self.service.apply_authorization(next_authorization, now=NOW + timedelta(seconds=40))
        self.assertNotEqual(resumed.session_id, session.session_id)
        commands = self.service.commands(3, now=NOW + timedelta(seconds=41))
        self.assertEqual([(c.kind, c.session_id) for c in commands], [("inicio", resumed.session_id)])
        self.assertEqual(self.service.inspection(3, session.session_id, now=ended + timedelta(seconds=2))["reception"],
                         "intervention_required")

    def test_physical_stop_can_be_enriched_but_not_changed(self):
        session = self.active()
        ended = NOW + timedelta(seconds=20)
        arguments = dict(ended_at=ended, reason_code="AGENT_STOPPED", now=ended + timedelta(seconds=1))
        self.service.confirm_capture_ended(3, session.session_id, **arguments)
        self.service.confirm_capture_ended(3, session.session_id, last_sequence=0, **arguments)
        self.assertEqual(CaptureSession.objects.get().final_sequence, 0)
        self.assertEqual(CaptureSession.objects.get().diagnostic_code, "")
        self.assert_code("CONFIRMATION_CONFLICT", self.service.confirm_capture_ended,
                         3, session.session_id, last_sequence=1, **arguments)
        self.assertTrue(self.accept(session, received=2 * 86400))
        self.assertEqual(CaptureSession.objects.get().state, "completada")

    def test_real_capture_failure_remains_failed_but_confirmed_physical_stop_preserves_valid_pending(self):
        session = self.active()
        self.service.interrupted(3, session.session_id, now=NOW + timedelta(seconds=20))
        self.service.confirm_capture_ended(3, session.session_id, ended_at=NOW + timedelta(seconds=20),
            last_sequence=0, reason_code="AGENT_INTERRUPTED", now=NOW + timedelta(seconds=21))
        self.assertTrue(self.accept(session, received=86400))
        self.assertEqual(CaptureSession.objects.get().state, "fallida")
        self.assertEqual(CaptureSession.objects.get().error_code, "AGENT_INTERRUPTED")
        snapshot = self.service.inspection(3, session.session_id, now=NOW + timedelta(days=10))
        self.assertEqual(snapshot["reception"], "complete")
        self.assertNotEqual(snapshot["diagnostic_code"], "RECEPTION_INTERVENTION_REQUIRED")

    def test_interrupted_physical_report_preserves_failure_without_websocket_interruption(self):
        session = self.active()
        ended = NOW + timedelta(seconds=20)
        self.service.confirm_capture_ended(3, session.session_id, ended_at=ended,
            last_sequence=0, reason_code="AGENT_INTERRUPTED", now=ended + timedelta(seconds=1))
        self.assertTrue(self.accept(session, received=86400))
        stored = CaptureSession.objects.get()
        self.assertEqual(stored.state, "fallida")
        self.assertEqual(stored.error_code, "AGENT_INTERRUPTED")
        self.assertEqual(self.service.inspection(3, session.session_id, now=NOW + timedelta(days=1))["reception"], "complete")
        count = CaptureEvent.objects.count()
        self.service.confirm_capture_ended(3, session.session_id, ended_at=ended,
            last_sequence=0, reason_code="AGENT_INTERRUPTED", now=NOW + timedelta(days=1))
        self.assertEqual(CaptureEvent.objects.count(), count)

    def test_disk_low_report_keeps_technical_failure_and_specific_cause(self):
        session = self.active()
        self.service.confirm_capture_ended(3, session.session_id, ended_at=NOW + timedelta(seconds=20),
            last_sequence=-1, reason_code="DISK_LOW", now=NOW + timedelta(seconds=21))
        stored = CaptureSession.objects.get()
        self.assertEqual(stored.state, "fallida")
        self.assertEqual(stored.error_code, "AGENT_INTERRUPTED")
        self.assertEqual(stored.capture_end_reason, "DISK_LOW")

    def test_interrupted_physical_report_after_stop_ack_keeps_failure_visible(self):
        session = self.active()
        self.ack_stop(self.stop(), last_sequence=-1)
        self.assertEqual(CaptureSession.objects.get().state, "completada")
        self.service.confirm_capture_ended(3, session.session_id, ended_at=NOW + timedelta(seconds=35),
            last_sequence=-1, reason_code="AGENT_INTERRUPTED", now=NOW + timedelta(seconds=36))
        self.assertEqual(CaptureSession.objects.get().state, "fallida")
        self.assertEqual(CaptureSession.objects.get().error_code, "AGENT_INTERRUPTED")

    def test_late_start_does_not_clear_unconfirmed_stop_diagnostic(self):
        self.create()
        start, = self.service.commands(3, now=NOW)
        self.service.commands(3, now=NOW + timedelta(days=1))
        self.service.recover(now=NOW + timedelta(days=1, minutes=10))
        self.service.acknowledge(3, start.command_id, occurred_at=NOW,
                                 now=NOW + timedelta(days=1, minutes=11))
        self.assertEqual(CaptureSession.objects.get().diagnostic_code, "STOP_CONFIRMATION_PENDING")

    def test_operator_can_recover_legacy_timeout_without_reactivating_capture(self):
        session = self.active()
        self.stop()
        CaptureSession.objects.filter(pk=session.session_id).update(
            state="fallida", error_code="SESSION_ABANDONED", closed_at=NOW + timedelta(minutes=10))
        self.service.resume_reception(3, session.session_id, now=NOW + timedelta(days=8))
        self.assertEqual(CaptureSession.objects.get().state, "finalizando")
        self.assertIsNone(CaptureSession.objects.get().actual_end)
        self.assertTrue(self.accept(session, received=8 * 86400 + 1))

    def test_operator_command_resumes_reception(self):
        session = self.active()
        self.ack_stop(self.stop(), last_sequence=0)
        with patch("django.utils.timezone.now", return_value=NOW + timedelta(days=8)):
            output = StringIO()
            call_command("resume_capture_reception", box="box-3", session_id=str(session.session_id),
                         days=7, stdout=output)
        self.assertIn("Recepción habilitada", output.getvalue())
        self.assertEqual(CaptureSession.objects.get().reception_extended_until, NOW + timedelta(days=15))


class OfflineIngestionContinuityTests(IngestionFixtures, TestCase):
    def test_receipt_lost_after_commit_is_identical_after_days_and_server_restart(self):
        self.ack_stop(self.stop(), last_sequence=0)
        first, _ = self.receive(now=NOW + timedelta(days=2))
        from .ingestion import FragmentIngestionService
        self.ingestion = FragmentIngestionService(self.storage, CaptureSessionService())
        count = CaptureEvent.objects.count()
        again, created = self.receive(now=NOW + timedelta(days=12))
        self.assertFalse(created)
        self.assertEqual(first, again)
        self.assertEqual(CaptureEvent.objects.count(), count)
        self.assertEqual(len(self.blobs()), 1)

    def test_complete_reception_is_distinct_from_pending_processing(self):
        self.ack_stop(self.stop(), last_sequence=0)
        self.receive(now=NOW + timedelta(days=2))
        snapshot = self.service.inspection(3, self.session.session_id, now=NOW + timedelta(days=2))
        self.assertEqual(snapshot["capture"], "finished")
        self.assertEqual(snapshot["reception"], "complete")
        self.assertEqual(snapshot["processing"], "pending")
        self.assertEqual(snapshot["job_counts"]["pendiente"], 1)
