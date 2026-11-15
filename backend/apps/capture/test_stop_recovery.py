import json
from dataclasses import replace
from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.test import TestCase

from .authentication import AgentIdentity
from .models import AcceptedSequence, AgentCommand, CaptureEvent, CaptureSession, CommandKind, SessionState
from .services import STOP_CONFIRMATION_ESCALATED
from .test_ingestion import IngestionFixtures
from .tests import CaptureFixtures, NOW
from .websocket import RemoteControl

CUT = NOW + timedelta(seconds=30)
UNDELIVERED_START_EVENT = "capture.start.cancelled_before_delivery"


class UndeliveredStartTests(CaptureFixtures, TestCase):
    def assert_closed_without_stop(self, expected_cut):
        saved = CaptureSession.objects.get()
        self.assertEqual(saved.state, SessionState.COMPLETED)
        self.assertEqual(saved.stop_requested_at, expected_cut)
        self.assertEqual(saved.actual_end, expected_cut)
        self.assertIsNone(saved.actual_start)
        self.assertEqual(saved.final_sequence, -1)
        self.assertEqual(saved.capture_end_reason, "RECOVERY_STOPPED")
        start = AgentCommand.objects.get()
        self.assertEqual(start.kind, CommandKind.START)
        self.assertEqual(start.cancelled_at, expected_cut)
        self.assertEqual(start.delivery_count, 0)
        self.assertIsNone(start.delivered_at)
        self.assertIsNone(start.acknowledged_at)
        self.assertIsNone(start.succeeded)
        self.assertEqual(CaptureEvent.objects.get(action=UNDELIVERED_START_EVENT).command_id, start.pk)
        self.assertEqual(CaptureEvent.objects.filter(action="capture.session.completed").count(), 1)

    def test_expiry_closes_without_creating_stop(self):
        self.create()
        self.assertEqual(self.service.recover(now=self.authorization.termino), 1)
        self.assert_closed_without_stop(self.authorization.termino)

    def test_revocation_closes_without_creating_stop(self):
        self.create()
        self.revoke()
        self.revoke()
        self.assert_closed_without_stop(CUT)
        self.assertEqual(self.service.commands(3, now=CUT), ())

    def test_coordinator_stop_all_closes_without_creating_stop(self):
        self.create()
        with patch("django.utils.timezone.now", return_value=CUT):
            call_command("coordinate_capture", stop_all=True)
        self.assert_closed_without_stop(CUT)
        resumed = self.service.apply_authorization(self.authorization, now=CUT)
        self.assertEqual(resumed.state, SessionState.STARTED)
        self.assertNotEqual(resumed.session_id, CaptureSession.objects.get(state=SessionState.COMPLETED).pk)

    def test_interruption_keeps_the_technical_failure(self):
        session = self.create()
        result = self.service.interrupted(3, session.session_id, error_code="AGENT_START_FAILED", now=CUT)
        self.assertEqual(result.state, SessionState.FAILED)
        self.assertEqual(result.error_code, "AGENT_START_FAILED")
        self.assertEqual(CaptureSession.objects.get().closed_at, CUT)
        self.assertEqual(result.actual_end, CUT)
        self.assertEqual(result.final_sequence, -1)
        self.assertFalse(AgentCommand.objects.filter(kind=CommandKind.STOP).exists())
        self.assertFalse(CaptureEvent.objects.filter(action="capture.session.completed").exists())
        self.assertEqual(CaptureEvent.objects.filter(action=UNDELIVERED_START_EVENT).count(), 1)

    def test_missing_start_uses_a_normal_stop(self):
        self.create()
        AgentCommand.objects.filter(kind=CommandKind.START).delete()
        stop = self.stop()
        self.assertEqual(stop.kind, CommandKind.STOP)
        self.assertIsNone(CaptureSession.objects.get().actual_end)
        self.assertEqual(self.ack_stop(stop, last_sequence=-1).state, SessionState.COMPLETED)
        self.assertFalse(CaptureEvent.objects.filter(action=UNDELIVERED_START_EVENT).exists())


class HistoricalStopRecoveryTests(CaptureFixtures, TestCase):
    def historical_session(self, now, *, state=SessionState.STOPPING, **fields):
        session = CaptureSession.objects.get(pk=self.create().session_id)
        CaptureSession.objects.filter(pk=session.pk).update(state=state, stop_requested_at=CUT, **fields)
        session.commands.filter(kind=CommandKind.START).update(cancelled_at=CUT)
        stop = session.commands.create(kind=CommandKind.STOP, created_at=CUT,
                                       delivery_count=883, delivered_at=now - timedelta(seconds=5))
        return session, stop

    def test_recovers_box_3_once_and_discards_prepared_wss_stop(self):
        now = NOW + timedelta(days=1)
        session, stop = self.historical_session(now)
        window = replace(self.authorization, inicio=now, termino=now + timedelta(hours=1))
        self.assertEqual(self.service.apply_authorization(window, now=now).session_id, session.pk)
        with patch("django.utils.timezone.now", return_value=now):
            control = RemoteControl(AgentIdentity("synthetic-box-3", "box-3"), uuid4())
            control.open()
            prepared, = control.poll()
            self.assertEqual(prepared["command_id"], str(stop.pk))
            self.assertTrue(control.still_current(prepared))
            commands_before = list(session.commands.order_by("pk").values())
            for changed in (1, 0):
                output = StringIO()
                call_command("recover_capture_sessions", stdout=output)
                self.assertIn(f"Sesiones actualizadas: {changed}", output.getvalue())
            self.assertFalse(control.still_current(prepared))
            session.refresh_from_db()
            self.assertEqual((session.state, session.actual_end, session.final_sequence),
                             (SessionState.COMPLETED, CUT, -1))
            self.assertEqual(CaptureEvent.objects.filter(action=UNDELIVERED_START_EVENT).count(), 1)
            self.assertEqual(CaptureEvent.objects.filter(action="capture.session.completed").count(), 1)
            self.assertEqual(list(session.commands.order_by("pk").values()), commands_before)
            resumed = self.service.apply_authorization(window, now=now)
            self.assertNotEqual(resumed.session_id, session.pk)
            start, = control.poll()
            self.assertEqual((start["kind"], start["session_id"]), (CommandKind.START, str(resumed.session_id)))
            self.assertEqual(self.service.acknowledge(3, start["command_id"], now=now).state, SessionState.ACTIVE)

    def test_recovers_failed_blocker_and_preserves_failure_metadata(self):
        now = NOW + timedelta(minutes=20)
        closed = CUT + timedelta(minutes=10)
        session, _ = self.historical_session(now, state=SessionState.FAILED, closed_at=closed,
                                             error_code="FINAL_SEQUENCE_TIMEOUT", final_sequence=-1)
        self.assertIsNone(self.service.apply_authorization(self.authorization, now=now))
        self.assertEqual(self.service.recover(now=now), 1)
        self.assertEqual(self.service.recover(now=now), 0)
        session.refresh_from_db()
        self.assertEqual((session.state, session.error_code, session.closed_at),
                         (SessionState.FAILED, "FINAL_SEQUENCE_TIMEOUT", closed))
        self.assertEqual((session.actual_end, session.final_sequence), (CUT, -1))
        self.assertEqual(session.events.filter(action=UNDELIVERED_START_EVENT).count(), 1)
        self.assertNotEqual(self.service.apply_authorization(self.authorization, now=now).session_id, session.pk)

    def test_drain_and_recovery_require_consistent_start_and_sequence_evidence(self):
        now = NOW + timedelta(days=1)
        session, _ = self.historical_session(now)
        order = session.commands.get(kind=CommandKind.START)
        with patch("django.utils.timezone.now", return_value=now):
            output = StringIO()
            call_command("recover_capture_sessions", check_drain=True, stdout=output)
            self.assertEqual(output.getvalue().strip(), "0")
        session.refresh_from_db()
        self.assertIsNone(session.actual_end)
        for changes in (
            {"delivery_count": 1}, {"delivered_at": NOW}, {"acknowledged_at": NOW},
            {"succeeded": True}, {"succeeded": False}, {"cancelled_at": None},
        ):
            with self.subTest(changes=changes):
                session.commands.filter(pk=order.pk).update(**changes)
                self.assertEqual(self.service.count_pending_drain(now=now), 1)
                self.service.recover(now=now)
                session.refresh_from_db()
                self.assertIsNone(session.actual_end)
                order.save(update_fields=list(changes))
        event = session.events.create(action="capture.command.delivered", command_id=order.pk,
                                      state=SessionState.STARTED, timestamp=NOW)
        self.assertEqual(self.service.count_pending_drain(now=now), 1)
        self.assertEqual(self.service.recover(now=now), 0)
        event.delete()
        AcceptedSequence.objects.create(session=session, number=0, captured_at=NOW, accepted_at=NOW)
        self.assertEqual(self.service.count_pending_drain(now=now), 1)
        self.assertEqual(self.service.recover(now=now), 0)
        session.refresh_from_db()
        self.assertIsNone(session.actual_end)
        self.assertIsNone(session.final_sequence)
        self.assertFalse(session.events.filter(action=UNDELIVERED_START_EVENT).exists())

    def test_recovery_rejects_missing_or_invalid_stop_timestamp(self):
        now = NOW + timedelta(days=1)
        session, _ = self.historical_session(now)
        for cutoff in (None, NOW - timedelta(seconds=1), now + timedelta(seconds=1)):
            with self.subTest(cutoff=cutoff):
                CaptureSession.objects.filter(pk=session.pk).update(stop_requested_at=cutoff)
                self.assertEqual(self.service.count_pending_drain(now=now), 1)
                self.service.recover(now=now)
                session.refresh_from_db()
                self.assertIsNone(session.actual_end)
                self.assertIsNone(session.final_sequence)


class StopEscalationTests(IngestionFixtures, TestCase):
    def test_escalation_keeps_capture_blocked_until_ack_then_accepts_audio(self):
        stop = self.stop()
        threshold = CUT + timedelta(minutes=60)
        before = threshold - timedelta(microseconds=1)
        window = replace(self.authorization, inicio=NOW + timedelta(minutes=45), termino=NOW + timedelta(hours=2))
        session = CaptureSession.objects.get()
        self.service.recover(now=before)
        session.refresh_from_db()
        self.assertEqual(session.diagnostic_code, "STOP_CONFIRMATION_PENDING")
        self.assertEqual(self.service.count_pending_drain(now=before), 1)
        self.assertEqual(self.service.recover(now=threshold), 1)
        self.assertEqual(self.service.recover(now=threshold + timedelta(seconds=1)), 0)
        self.assertEqual(session.events.filter(error_code=STOP_CONFIRMATION_ESCALATED).count(), 1)
        self.assertIsNone(self.service.apply_authorization(window, now=threshold).actual_end)
        session.refresh_from_db()
        self.assertEqual(session.state, SessionState.STOPPING)
        self.assertIsNone(session.actual_end)
        self.assertIsNone(session.final_sequence)
        self.assertEqual(self.service.count_pending_drain(now=threshold), 1)
        output = StringIO()
        with patch("django.utils.timezone.now", return_value=threshold):
            call_command("capture_health", stdout=output)
        self.assertEqual(json.loads(output.getvalue())["backlog_counts"]["capture_stop_escalated"], 1)

        reconnect = threshold + timedelta(hours=1)
        self.assertEqual(self.service.commands(3, now=reconnect)[0].command_id, stop.command_id)
        stopped = self.service.acknowledge(3, stop.command_id, occurred_at=CUT, last_sequence=0, now=reconnect)
        self.assertEqual(stopped.state, SessionState.STOPPING)
        self.assertEqual(stopped.actual_end, CUT)
        self.assertEqual(self.service.count_pending_drain(now=reconnect), 0)
        window = replace(window, termino=reconnect + timedelta(hours=1))
        resumed = self.service.apply_authorization(window, now=reconnect)
        self.assertNotEqual(resumed.session_id, session.pk)
        start, = self.service.commands(3, now=reconnect)
        self.assertEqual(self.service.acknowledge(3, start.command_id, now=reconnect).state, SessionState.ACTIVE)
        _, created = self.receive(now=reconnect + timedelta(seconds=1))
        self.assertTrue(created)
        session.refresh_from_db()
        self.assertEqual(session.state, SessionState.COMPLETED)
        self.assertEqual(session.diagnostic_code, "")

    def test_failed_stop_still_escalates_once_and_blocks_the_box(self):
        stop = self.stop()
        self.service.acknowledge(3, stop.command_id, success=False, now=CUT + timedelta(seconds=5))
        threshold = CUT + timedelta(hours=1)
        self.assertEqual(self.service.recover(now=threshold), 1)
        self.assertEqual(self.service.recover(now=threshold + timedelta(minutes=1)), 0)
        session = CaptureSession.objects.get()
        self.assertEqual(session.state, SessionState.FAILED)
        self.assertEqual(session.error_code, "AGENT_STOP_FAILED")
        self.assertEqual(session.diagnostic_code, STOP_CONFIRMATION_ESCALATED)
        self.assertEqual(session.events.filter(error_code=STOP_CONFIRMATION_ESCALATED).count(), 1)
        self.assertIsNone(session.actual_end)
        self.assertIsNone(session.final_sequence)
        self.assertEqual(self.service.count_pending_drain(now=threshold), 1)
        window = replace(self.authorization, inicio=threshold, termino=threshold + timedelta(hours=1))
        self.assertIsNone(self.service.apply_authorization(window, now=threshold))
