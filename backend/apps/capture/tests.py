from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.db import IntegrityError, close_old_connections, connections, transaction
from django.test import TestCase, TransactionTestCase

from backend.apps.operational.capture_authorization import BoxCaptureAuthorization
from backend.apps.operational.models import OperationalConfiguration
from backend.apps.operational.services import OperationalService
from backend.config.composition import capture_session_service
from .domain import CaptureError
from .models import AcceptedSequence, AgentCommand, CaptureEvent, CaptureSession, CommandKind, SessionState
from .services import CaptureSessionService

NOW = datetime(2026, 10, 19, 12, tzinfo=dt_timezone.utc)


class CaptureFixtures:
    def setUp(self):
        super().setUp()
        self.service = CaptureSessionService()
        self.authorization = BoxCaptureAuthorization("box-3", True, NOW, NOW + timedelta(hours=1), "agenda")

    def create(self):
        return self.service.apply_authorization(self.authorization, now=NOW)

    def active(self):
        session = self.create()
        command, = self.service.commands("box-3", now=NOW)
        self.service.acknowledge("box-3", command.command_id, now=NOW)
        return session

    def stop(self):
        denied = replace(self.authorization, authorized=False, inicio=None, termino=None)
        self.service.apply_authorization(denied, now=NOW + timedelta(seconds=30))
        command, = self.service.commands("box-3", now=NOW + timedelta(seconds=31))
        return command

    def ack_stop(self, command, last_sequence=0):
        return self.service.acknowledge("box-3", command.command_id, last_sequence=last_sequence,
                                        now=NOW + timedelta(seconds=35))

    def accept(self, session, number=0, seconds=10, received=20):
        return self.service.accept_sequence("box-3", session.session_id, number,
                                            NOW + timedelta(seconds=seconds), now=NOW + timedelta(seconds=received))

    def assert_code(self, code, function, *args, **kwargs):
        with self.assertRaises(CaptureError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)


class CaptureLifecycleTests(CaptureFixtures, TestCase):
    def test_creation_is_persistent_unique_and_recoverable_after_service_restart(self):
        session = self.create()
        self.assertEqual(session.state, "iniciada")
        self.assertIsNotNone(session.session_id)
        self.assertEqual(session.origin, "agenda")
        restarted = CaptureSessionService()
        same = restarted.apply_authorization(self.authorization, now=NOW)
        self.assertEqual(same.session_id, session.session_id)
        self.assertEqual(CaptureSession.objects.count(), 1)
        self.assertEqual(AgentCommand.objects.count(), 1)
        self.assertEqual(list(CaptureEvent.objects.values_list("action", flat=True)).count("capture.session.created"), 1)

    def test_start_command_sees_saved_session_and_rolls_back_together(self):
        original = self.service._command

        def check_saved(session, *args):
            self.assertTrue(CaptureSession.objects.filter(pk=session.pk).exists())
            original(session, *args)
            raise RuntimeError("simulated crash")

        with patch.object(self.service, "_command", side_effect=check_saved):
            with self.assertRaises(RuntimeError):
                self.create()
        self.assertEqual(CaptureSession.objects.count(), 0)
        self.assertEqual(AgentCommand.objects.count(), 0)
        self.assertEqual(CaptureEvent.objects.count(), 0)

    def test_denied_does_not_create_session(self):
        self.service.apply_authorization(replace(self.authorization, authorized=False), now=NOW)
        self.assertFalse(CaptureSession.objects.exists())

    def test_reauthorization_of_same_fallback_window_creates_new_session_after_restart(self):
        self.authorization = replace(self.authorization, origen="horario_clinico")
        original = self.active()
        self.ack_stop(self.stop(), last_sequence=-1)
        restarted = CaptureSessionService()
        now = NOW + timedelta(seconds=40)
        resumed = restarted.apply_authorization(self.authorization, now=now)
        self.assertNotEqual(resumed.session_id, original.session_id)
        self.assertEqual(resumed.state, "iniciada")
        self.assertEqual(resumed.origin, "horario_clinico")
        self.assertEqual(CaptureSession.objects.get(pk=original.session_id).state, "completada")
        self.assertEqual(restarted.apply_authorization(self.authorization, now=now), resumed)
        command, = restarted.commands(3, now=now)
        self.assertEqual(command.session_id, resumed.session_id)
        self.assertEqual(command.kind, "inicio")
        self.assertEqual(CaptureSession.objects.count(), 2)

    def test_reauthorization_waits_for_previous_session_to_finish(self):
        original = self.active()
        stop = self.stop()
        waiting = self.service.apply_authorization(self.authorization, now=NOW + timedelta(seconds=32))
        self.assertEqual(waiting.session_id, original.session_id)
        self.assertEqual(waiting.state, "finalizando")
        self.assertEqual(CaptureSession.objects.count(), 1)
        self.ack_stop(stop, last_sequence=0)
        self.accept(original, received=36)
        resumed = self.service.apply_authorization(self.authorization, now=NOW + timedelta(seconds=40))
        self.assertNotEqual(resumed.session_id, original.session_id)

    def test_repeated_revocations_record_authorization_end_once(self):
        original = self.active()
        self.stop()
        denied = replace(self.authorization, authorized=False)
        CaptureSessionService().apply_authorization(denied, now=NOW + timedelta(seconds=32))
        session = CaptureSession.objects.get(pk=original.session_id)
        self.assertEqual(session.authorization_ended_at, NOW + timedelta(seconds=30))
        self.assertEqual(session.events.filter(action="capture.authorization.ended").count(), 1)

    def test_failed_session_does_not_restart_without_a_new_authorization(self):
        original = self.active()
        self.service.interrupted(3, original.session_id, now=NOW + timedelta(seconds=10))
        stop, = self.service.commands(3, now=NOW + timedelta(seconds=11))
        self.service.acknowledge(3, stop.command_id, last_sequence=-1, now=NOW + timedelta(seconds=12))
        restarted = CaptureSessionService()
        repeated = restarted.apply_authorization(self.authorization, now=NOW + timedelta(seconds=20))
        self.assertEqual(repeated.session_id, original.session_id)
        self.assertEqual(repeated.state, "fallida")
        self.assertEqual(restarted.commands(3, now=NOW + timedelta(seconds=20)), ())
        self.assertEqual(CaptureSession.objects.count(), 1)

    def test_revocation_of_failed_session_allows_reauthorization_only_after_cleanup(self):
        original = self.active()
        self.service.interrupted(3, original.session_id, now=NOW + timedelta(seconds=10))
        denied = replace(self.authorization, authorized=False)
        self.service.apply_authorization(denied, now=NOW + timedelta(seconds=15))
        now = NOW + timedelta(seconds=20)
        self.assertIsNone(self.service.apply_authorization(self.authorization, now=now))
        stop, = self.service.commands(3, now=now)
        self.service.acknowledge(3, stop.command_id, last_sequence=-1, now=now)
        resumed = CaptureSessionService().apply_authorization(self.authorization, now=now)
        self.assertNotEqual(resumed.session_id, original.session_id)
        self.assertEqual(resumed.state, "iniciada")

    def test_returning_to_fallback_after_agenda_creates_new_session_in_same_window(self):
        fallback = replace(self.authorization, origen="horario_clinico")
        first = self.service.apply_authorization(fallback, now=NOW)
        start, = self.service.commands(3, now=NOW)
        self.service.acknowledge(3, start.command_id, now=NOW)
        for authorization, seconds in ((self.authorization, 10), (fallback, 20)):
            now = NOW + timedelta(seconds=seconds)
            self.service.apply_authorization(authorization, now=now)
            stop, = self.service.commands(3, now=now)
            self.service.acknowledge(3, stop.command_id, last_sequence=-1, now=now)
            resumed = CaptureSessionService().apply_authorization(authorization, now=now)
            self.assertEqual(resumed.state, "iniciada")
            start, = self.service.commands(3, now=now)
            self.service.acknowledge(3, start.command_id, now=now)
        self.assertNotEqual(resumed.session_id, first.session_id)
        self.assertEqual(resumed.origin, "horario_clinico")
        self.assertEqual(CaptureSession.objects.count(), 3)

    def test_commands_are_retried_with_same_id_until_acknowledged(self):
        self.create()
        first, = self.service.commands(3, now=NOW)
        retry, = CaptureSessionService().commands(3, now=NOW)
        self.assertEqual(first, retry)
        self.assertEqual(AgentCommand.objects.get().delivery_count, 2)
        result = self.service.acknowledge(3, first.command_id, now=NOW)
        self.assertEqual(result.state, "activa")
        self.assertEqual(result.actual_start, NOW)
        self.assertEqual(self.service.commands(3, now=NOW), ())
        self.assertEqual(self.service.acknowledge(3, first.command_id, now=NOW), result)

    def test_ack_requires_delivery_correct_box_and_existing_command(self):
        self.create()
        command = AgentCommand.objects.get()
        self.assert_code("COMMAND_NOT_DELIVERED", self.service.acknowledge, 3, command.pk, now=NOW)
        self.assert_code("COMMAND_NOT_FOUND", self.service.acknowledge, 4, command.pk, now=NOW)
        self.assert_code("COMMAND_NOT_FOUND", self.service.acknowledge, 3, uuid4(), now=NOW)

    def test_revocation_cancels_undelivered_start_and_generates_one_stop(self):
        self.create()
        stop = self.stop()
        self.assertEqual(stop.kind, "detencion")
        self.stop()
        self.assertEqual(AgentCommand.objects.filter(kind=CommandKind.STOP).count(), 1)
        self.assertIsNotNone(AgentCommand.objects.get(kind=CommandKind.START).cancelled_at)
        result = self.ack_stop(stop, last_sequence=-1)
        self.assertEqual(result.state, "completada")
        self.assertIsNone(result.actual_start)

    def test_complete_only_after_stop_ack_and_final_sequence_arrives(self):
        session = self.active()
        stop = self.stop()
        result = self.ack_stop(stop, last_sequence=1)
        self.assertEqual(result.state, "finalizando")
        self.accept(session, received=40)
        self.assertEqual(CaptureSession.objects.get().state, "finalizando")
        self.accept(session, 1, seconds=20, received=41)
        saved = CaptureSession.objects.get()
        self.assertEqual(saved.state, "completada")
        self.assertEqual(saved.next_sequence, 2)
        self.assertEqual(saved.actual_end, NOW + timedelta(seconds=35))
        self.assertIsNotNone(saved.closed_at)
        self.assertEqual(CaptureEvent.objects.filter(action="capture.session.completed").count(), 1)
        self.assertFalse(self.accept(session, 1, seconds=20, received=42))

    def test_final_sequence_before_stop_ack_waits_for_confirmation(self):
        session = self.active()
        self.accept(session)
        stop = self.stop()
        self.assertEqual(CaptureSession.objects.get().state, "finalizando")
        self.assertEqual(self.ack_stop(stop).state, "completada")
        self.ack_stop(stop)
        self.assertEqual(CaptureEvent.objects.filter(action="capture.session.completed").count(), 1)

    def test_sequences_are_contiguous_idempotent_and_validate_capture_window(self):
        session = self.active()
        self.assert_code("SEQUENCE_OUT_OF_ORDER", self.accept, session, 1)
        self.assert_code("SEQUENCE_OUTSIDE_CAPTURE_WINDOW", self.accept, session, seconds=-1)
        self.assert_code("INVALID_SEQUENCE", self.accept, session, True)
        self.assert_code("INVALID_SEQUENCE", self.accept, session, -1)
        self.assertTrue(self.accept(session))
        self.assertFalse(self.accept(session))
        self.assert_code("SEQUENCE_CONFLICT", self.accept, session, seconds=11)
        self.assert_code("INVALID_TIMESTAMP", self.accept, session, 1, seconds=9)
        self.assertEqual(AcceptedSequence.objects.count(), 1)
        self.assertEqual(CaptureEvent.objects.filter(action="capture.sequence.accepted").count(), 1)

    def test_stop_rejects_inconsistent_last_sequence_and_ack_conflicts(self):
        session = self.active()
        self.accept(session)
        stop = self.stop()
        self.assert_code("INVALID_FINAL_SEQUENCE", self.ack_stop, stop, -1)
        self.assert_code("INVALID_FINAL_SEQUENCE", self.ack_stop, stop, True)
        self.ack_stop(stop, 0)
        self.assert_code("CONFIRMATION_CONFLICT", self.ack_stop, stop, 1)

    def test_no_sequences_before_start_after_terminal_state_or_from_other_box(self):
        session = self.create()
        self.assert_code("SESSION_NOT_ACCEPTING_SEQUENCES", self.accept, session)
        self.assert_code("SESSION_NOT_FOUND", self.service.accept_sequence, 4, session.session_id, 0, NOW, now=NOW)
        self.service.interrupted(3, session.session_id, now=NOW)
        self.assert_code("SESSION_NOT_ACCEPTING_SEQUENCES", self.accept, session)

    def test_sequences_cannot_extend_past_revocation_or_announced_final(self):
        session = self.active()
        stop = self.stop()
        self.ack_stop(stop, 0)
        self.assert_code("SEQUENCE_OUTSIDE_CAPTURE_WINDOW", self.accept, session, seconds=31, received=40)
        self.accept(session, received=40)
        self.assert_code("SESSION_NOT_ACCEPTING_SEQUENCES", self.accept, session, 1, seconds=20, received=40)

    def test_start_failure_is_technical_and_requests_cleanup(self):
        self.create()
        command, = self.service.commands(3, now=NOW)
        result = self.service.acknowledge(3, command.command_id, success=False, now=NOW)
        self.assertEqual(result.state, "fallida")
        self.assertEqual(result.error_code, "AGENT_START_FAILED")
        stop, = self.service.commands(3, now=NOW)
        self.assertEqual(stop.kind, "detencion")
        self.assert_code("INVALID_CONFIRMATION", self.service.acknowledge, 3, stop.command_id,
                         success=False, error_code="sensitive free text", now=NOW)

    def test_stop_failure_is_retried_and_blocks_new_authorization_until_cleanup(self):
        self.active()
        stop = self.stop()
        self.service.acknowledge(3, stop.command_id, success=False, now=NOW + timedelta(seconds=35))
        self.assertEqual(CaptureSession.objects.get().state, "fallida")
        next_window = replace(self.authorization, inicio=NOW + timedelta(seconds=40))
        self.assertIsNone(self.service.apply_authorization(next_window, now=NOW + timedelta(seconds=40)))
        retry, = self.service.commands(3, now=NOW + timedelta(seconds=40))
        self.assertEqual(retry.command_id, stop.command_id)
        self.service.acknowledge(3, stop.command_id, last_sequence=-1, now=NOW + timedelta(seconds=41))
        next_session = self.service.apply_authorization(next_window, now=NOW + timedelta(seconds=42))
        self.assertEqual(next_session.state, "iniciada")
        self.assertEqual(CaptureSession.objects.count(), 2)

    def test_recovery_stops_expired_window_without_delivering_start(self):
        self.create()
        commands = CaptureSessionService().commands(3, now=self.authorization.termino)
        self.assertEqual([item.kind for item in commands], ["detencion"])
        self.assertEqual(CaptureSession.objects.get().state, "finalizando")

    def test_recovery_diagnoses_missing_start_without_closing_and_is_idempotent(self):
        self.create()
        now = NOW + timedelta(minutes=2)
        self.assertEqual(CaptureSessionService().recover(now=now), 1)
        self.assertEqual(CaptureSessionService().recover(now=now), 0)
        self.assertEqual(CaptureSession.objects.get().diagnostic_code, "START_CONFIRMATION_PENDING")
        self.assertEqual(CaptureSession.objects.get().error_code, "")
        self.assertIsNone(CaptureSession.objects.get().closed_at)

    def test_missing_heartbeat_is_diagnostic_and_recovery_keeps_authorized_session(self):
        session = self.active()
        self.service.heartbeat(3, session.session_id, now=NOW + timedelta(seconds=90))
        self.service.recover(now=NOW + timedelta(seconds=150))
        self.assertEqual(CaptureSession.objects.get().state, "activa")
        self.service.recover(now=NOW + timedelta(seconds=210))
        self.assertEqual(CaptureSession.objects.get().diagnostic_code, "CONTROL_DISCONNECTED")
        result = self.service.heartbeat(3, session.session_id, now=NOW + timedelta(seconds=211))
        self.assertEqual(result.state, "activa")
        self.assertEqual(result.error_code, "")
        self.assertEqual(CaptureSession.objects.get().diagnostic_code, "")

    def test_delayed_heartbeat_cannot_move_activity_backwards(self):
        session = self.active()
        self.service.heartbeat(3, session.session_id, now=NOW + timedelta(seconds=90))
        self.service.heartbeat(3, session.session_id, now=NOW + timedelta(seconds=60))
        self.assertEqual(CaptureSession.objects.get().last_seen_at, NOW + timedelta(seconds=90))

    def test_delayed_start_confirmation_does_not_revive_failed_session(self):
        self.create()
        start, = self.service.commands(3, now=NOW)
        self.service.interrupted(3, start.session_id, now=NOW + timedelta(seconds=10))
        result = self.service.acknowledge(3, start.command_id, occurred_at=NOW,
                                          now=NOW + timedelta(seconds=121))
        self.assertEqual(result.state, "fallida")
        self.assertEqual(result.actual_start, NOW)
        self.assertEqual(result.error_code, "AGENT_INTERRUPTED")
        stop, = self.service.commands(3, now=NOW + timedelta(seconds=121))
        self.assertEqual(stop.kind, "detencion")

    def test_different_boxes_have_independent_sessions(self):
        first = self.create()
        second = self.service.apply_authorization(replace(self.authorization, box="box-4"), now=NOW)
        self.assertNotEqual(first.session_id, second.session_id)
        self.assertEqual(CaptureSession.objects.filter(state="iniciada").count(), 2)
        self.assertEqual([item.box for item in self.service.commands(4, now=NOW)], ["box-4"])

    def test_missing_final_sequence_survives_old_finalization_timeout(self):
        session = self.active()
        self.ack_stop(self.stop(), 1)
        now = NOW + timedelta(minutes=6)
        self.service.heartbeat(3, session.session_id, now=now)
        self.assertEqual(CaptureSession.objects.get().error_code, "")
        self.assertEqual(CaptureSession.objects.get().state, "finalizando")
        self.assertTrue(self.accept(session, received=361))

    def test_late_sequence_after_disconnect_is_accepted_without_extending_capture_window(self):
        session = self.active()
        self.assertTrue(self.accept(session, received=121))
        self.assertEqual(CaptureSession.objects.get().state, "activa")
        self.assert_code("SEQUENCE_OUTSIDE_CAPTURE_WINDOW", self.accept, session, number=1,
                         seconds=3601, received=4000)

    def test_missing_stop_confirmation_remains_pending_with_diagnostic(self):
        self.active()
        self.stop()
        self.service.recover(now=NOW + timedelta(minutes=6))
        self.assertEqual(CaptureSession.objects.get().diagnostic_code, "STOP_CONFIRMATION_PENDING")
        self.assertEqual(CaptureSession.objects.get().error_code, "")
        self.assertEqual(CaptureSession.objects.get().state, "finalizando")

    def test_reported_interruption_is_persistent_idempotent_and_blocks_late_sequences(self):
        session = self.active()
        for _ in range(2):
            self.service.interrupted(3, session.session_id, now=NOW + timedelta(seconds=20))
        self.assertEqual(CaptureSession.objects.get().state, "fallida")
        self.assertEqual(CaptureEvent.objects.filter(action="capture.session.failed").count(), 1)
        self.assertEqual(AgentCommand.objects.filter(kind=CommandKind.STOP).count(), 1)

    def test_changed_authorization_window_stops_existing_session_without_overwriting_context(self):
        original = self.active()
        changed = replace(self.authorization, origen="horario_clinico", termino=NOW + timedelta(hours=2))
        result = self.service.apply_authorization(changed, now=NOW + timedelta(seconds=10))
        self.assertEqual(result.session_id, original.session_id)
        self.assertEqual(result.origin, "agenda")
        self.assertEqual(result.state, "finalizando")
        self.assertEqual(CaptureSession.objects.count(), 1)

    def test_invalid_authorization_and_timestamps_are_rejected(self):
        for changed in (replace(self.authorization, inicio=None), replace(self.authorization, origen="patient-name"),
                        replace(self.authorization, termino=NOW), replace(self.authorization, box="box-0")):
            with self.assertRaises(CaptureError):
                self.service.apply_authorization(changed, now=NOW)
        self.assert_code("INVALID_TIMESTAMP", self.service.apply_authorization, self.authorization, now=NOW.replace(tzinfo=None))

    def test_operational_scrum70_entry_point_persists_and_revokes_session(self):
        OperationalConfiguration.objects.create(enabled_days=[0], open_time="08:00", close_time="18:00")
        service = OperationalService()
        self.assertTrue(service.authorize_box_capture(3, NOW).authorized)
        self.assertEqual(CaptureSession.objects.get().origin, "horario_clinico")
        service.authorize_box_transition(3, NOW)
        self.assertEqual(CaptureSession.objects.count(), 1)
        OperationalConfiguration.objects.update(enabled_days=[])
        self.assertFalse(service.authorize_box_capture(3, NOW).authorized)
        self.assertEqual(CaptureSession.objects.get().state, "finalizando")

    def test_factory_uses_injected_scrum70_and_recovers_from_persisted_state(self):
        config = OperationalConfiguration(enabled_days=[0], open_time="08:00", close_time="18:00")
        service = capture_session_service(config_loader=lambda: config)
        self.assertEqual(service.reconcile_box(3, now=NOW).origin, "horario_clinico")
        self.assertEqual(service.reconcile_box(3, now=NOW).state, "iniciada")

    def test_operational_preserves_scrum70_naive_local_time_contract(self):
        OperationalConfiguration.objects.create(enabled_days=[0], open_time="08:00", close_time="18:00")
        local_time = datetime(2026, 10, 19, 9)
        service = OperationalService()
        self.assertTrue(service.authorize_box_capture(3, local_time).authorized)
        service.authorize_box_transition(3, local_time)
        self.assertEqual(CaptureSession.objects.get().authorized_at, NOW)

    def test_audit_integrity_failure_does_not_report_success_or_hide_rollback(self):
        self.active()
        denied = replace(self.authorization, authorized=False)
        with patch("backend.apps.capture.services._event", side_effect=IntegrityError("simulated failure")):
            with self.assertRaises(IntegrityError):
                self.service.apply_authorization(denied, now=NOW + timedelta(seconds=30))
        self.assertEqual(CaptureSession.objects.get().state, "activa")
        self.assertIsNone(CaptureSession.objects.get().authorization_ended_at)
        self.assertFalse(AgentCommand.objects.filter(kind=CommandKind.STOP).exists())

    def test_audit_is_durable_and_emitted_only_after_commit(self):
        with patch("backend.common.audit.AuditWriter.emit") as emit:
            with self.captureOnCommitCallbacks(execute=True):
                self.create()
                emit.assert_not_called()
            self.assertEqual(emit.call_count, 2)
        event = CaptureEvent.objects.get(action="capture.session.created")
        self.assertEqual(event.session.box, "box-3")
        self.assertEqual(str(event.event_id), emit.call_args_list[0].args[0]["event_id"])
        for model in (CaptureSession, AcceptedSequence, AgentCommand, CaptureEvent):
            fields = {item.name for item in model._meta.fields}
            self.assertFalse(fields & {"audio", "transcript", "patient", "payload", "file", "path", "description"})

    def test_management_recovery_command_uses_persisted_state(self):
        self.create()
        with patch("backend.apps.capture.services.timezone.now", return_value=NOW + timedelta(minutes=3)):
            output = StringIO()
            call_command("recover_capture_sessions", stdout=output)
        self.assertIn("Sesiones actualizadas: 1", output.getvalue())
        self.assertEqual(CaptureSession.objects.get().state, "iniciada")
        self.assertEqual(CaptureSession.objects.get().diagnostic_code, "START_CONFIRMATION_PENDING")


class CaptureConcurrencyTests(CaptureFixtures, TransactionTestCase):
    """Conexiones SQL independientes y barrera de arranque; sin mocks de ORM."""
    def race(self, *functions):
        barrier = Barrier(len(functions))

        def run(function):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return function()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(functions)) as executor:
            futures = [executor.submit(run, function) for function in functions]
            return [future.result(timeout=20) for future in futures]

    def test_concurrent_authorizations_create_one_session_and_start_order(self):
        sessions = self.race(*[lambda: CaptureSessionService().apply_authorization(self.authorization, now=NOW)] * 6)
        self.assertEqual(len({session.session_id for session in sessions}), 1)
        self.assertEqual(CaptureSession.objects.count(), 1)
        self.assertEqual(AgentCommand.objects.count(), 1)

    def test_concurrent_duplicate_sequences_accept_exactly_once(self):
        session = self.active()
        results = self.race(*[lambda: self.accept(session)] * 6)
        self.assertEqual(results.count(True), 1)
        self.assertEqual(AcceptedSequence.objects.count(), 1)
        self.assertEqual(CaptureSession.objects.get().next_sequence, 1)

    def test_concurrent_reauthorizations_create_one_new_session_and_start_order(self):
        original = self.active()
        self.ack_stop(self.stop(), last_sequence=-1)
        now = NOW + timedelta(seconds=40)
        sessions = self.race(*[
            lambda: CaptureSessionService().apply_authorization(self.authorization, now=now)
        ] * 6)
        self.assertEqual(len({session.session_id for session in sessions}), 1)
        self.assertNotEqual(sessions[0].session_id, original.session_id)
        self.assertEqual(CaptureSession.objects.count(), 2)
        self.assertEqual(AgentCommand.objects.filter(session_id=sessions[0].session_id, kind=CommandKind.START).count(), 1)
        self.assertEqual(CaptureEvent.objects.filter(action="capture.session.created").count(), 2)

    def test_concurrent_polls_preserve_command_identity_and_delivery_count(self):
        self.create()
        deliveries = self.race(*[lambda: self.service.commands(3, now=NOW)] * 4)
        self.assertEqual(len({delivery[0].command_id for delivery in deliveries}), 1)
        self.assertEqual(AgentCommand.objects.get().delivery_count, 4)

    def test_concurrent_stop_confirmations_complete_once(self):
        session = self.active()
        self.accept(session)
        stop = self.stop()
        results = self.race(*[lambda: self.ack_stop(stop)] * 4)
        self.assertTrue(all(result.state == "completada" for result in results))
        self.assertEqual(CaptureEvent.objects.filter(action="capture.session.completed").count(), 1)

    def test_sequence_racing_with_interruption_never_revives_session(self):
        session = self.active()

        def sequence():
            try:
                return self.accept(session)
            except CaptureError as exc:
                return exc.code

        self.race(sequence, lambda: self.service.interrupted(3, session.session_id, now=NOW + timedelta(seconds=20)))
        saved = CaptureSession.objects.get()
        self.assertEqual(saved.state, "fallida")
        self.assertEqual(saved.next_sequence, AcceptedSequence.objects.count())
        self.assertEqual(AgentCommand.objects.filter(kind=CommandKind.STOP).count(), 1)

    def test_concurrent_revocations_create_one_stop(self):
        self.active()
        self.race(*[self.stop] * 4)
        self.assertEqual(AgentCommand.objects.filter(kind=CommandKind.STOP).count(), 1)
        self.assertEqual(CaptureEvent.objects.filter(action="capture.session.stopping").count(), 1)
        self.assertEqual(CaptureEvent.objects.filter(action="capture.authorization.ended").count(), 1)

    def test_stop_confirmation_races_with_last_sequence_and_completes_once(self):
        session = self.active()
        stop = self.stop()
        self.race(lambda: self.ack_stop(stop), lambda: self.accept(session, received=35))
        self.assertEqual(CaptureSession.objects.get().state, "completada")
        self.assertEqual(CaptureEvent.objects.filter(action="capture.session.completed").count(), 1)

    def test_database_constraints_protect_even_direct_orm_writes(self):
        session = self.active()
        with self.assertRaises(IntegrityError), transaction.atomic():
            CaptureSession.objects.create(
                box="box-3", state="activa", origin="agenda", scheduled_start=NOW,
                scheduled_end=NOW + timedelta(hours=2), authorized_at=NOW, last_seen_at=NOW,
            )
        self.accept(session)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AcceptedSequence.objects.create(session_id=session.session_id, number=0, captured_at=NOW, accepted_at=NOW)
