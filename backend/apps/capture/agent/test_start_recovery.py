import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from backend.apps.capture.domain import Command

from .command_journal import CommandJournal
from .session_coordinator import SessionCoordinator


class StartRecoveryTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.config = SimpleNamespace(box_id="box-5")
        self.control = Mock()
        self.controller = Mock()
        self.runner_factory = Mock()
        self.journal = CommandJournal(self.temp.name, "box-5")

        now = datetime.now(timezone.utc)

        self.command = Command(
            command_id=uuid4(),
            session_id=uuid4(),
            box="box-5",
            kind="inicio",
            scheduled_start=now - timedelta(minutes=1),
            scheduled_end=now + timedelta(hours=1),
        )

        self.journal.prepare(self.command)

    def coordinator(self):
        return SessionCoordinator(
            config=self.config,
            control=self.control,
            controller=self.controller,
            runner_factory=self.runner_factory,
            journal=self.journal,
        )

    def mark_executed(self):
        self.journal.mark_executed(
            self.command,
            occurred_at=datetime.now(timezone.utc),
        )

    def assert_no_capture_started(self):
        self.controller.start_capture.assert_not_called()
        self.runner_factory.assert_not_called()
        self.control.acknowledge.assert_not_called()

    def test_inicio_preparado_requiere_reconciliacion(self):
        coordinator = self.coordinator()

        with self.assertRaisesRegex(RuntimeError, "reconciliacion"):
            coordinator.handle_command(self.command)

        self.control.interrupted.assert_not_called()
        self.assert_no_capture_started()

    def test_inicio_ejecutado_reporta_interrupcion(self):
        self.mark_executed()
        coordinator = self.coordinator()

        with self.assertRaisesRegex(RuntimeError, "CaptureRunner"):
            coordinator.handle_command(self.command)

        self.control.interrupted.assert_called_once_with(
            "box-5",
            self.command.session_id,
            error_code="AGENT_INTERRUPTED",
        )

        self.assert_no_capture_started()

    def test_inicio_confirmado_no_se_ejecuta_otra_vez(self):
        self.mark_executed()
        self.journal.mark_acknowledged(self.command)

        coordinator = self.coordinator()

        with self.assertRaises(RuntimeError):
            coordinator.handle_command(self.command)

        self.control.interrupted.assert_called_once()
        self.assert_no_capture_started()

    def test_no_duplica_notificacion_en_mismo_proceso(self):
        self.mark_executed()
        coordinator = self.coordinator()

        for _ in range(2):
            with self.assertRaises(RuntimeError):
                coordinator.handle_command(self.command)

        self.control.interrupted.assert_called_once()
        self.assert_no_capture_started()

    def test_reintenta_notificacion_si_falla_transporte(self):
        self.mark_executed()

        self.control.interrupted.side_effect = [
            TimeoutError("Backend no disponible"),
            None,
        ]

        coordinator = self.coordinator()

        with self.assertRaises(TimeoutError):
            coordinator.handle_command(self.command)

        with self.assertRaises(RuntimeError):
            coordinator.handle_command(self.command)

        self.assertEqual(self.control.interrupted.call_count, 2)
        self.assert_no_capture_started()


if __name__ == "__main__":
    unittest.main()
