import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from backend.apps.capture.domain import Command

from .command_journal import CommandJournal
from .session_coordinator import SessionCoordinator


class AutoStopRecoveryTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.config = SimpleNamespace(box_id="box-5")
        self.control = Mock()
        self.controller = Mock()
        self.journal = CommandJournal(self.temp.name, "box-5")

        now = datetime.now(timezone.utc)

        self.command = Command(
            command_id=uuid4(),
            session_id=uuid4(),
            box="box-5",
            kind="detencion",
            scheduled_start=now - timedelta(minutes=1),
            scheduled_end=now + timedelta(hours=1),
        )

        self.stopped_at = now
        self.journal.prepare(self.command)

        self.controller.status.return_value = {
            "recording": False,
            "streaming": False,
        }

    def make_coordinator(self):
        return SessionCoordinator(
            config=self.config,
            control=self.control,
            controller=self.controller,
            journal=self.journal,
        )

    def executed(self, last_sequence=4):
        self.journal.mark_executed(
            self.command,
            occurred_at=self.stopped_at,
            last_sequence=last_sequence,
        )

    def test_recupera_detencion_desde_handle_command(self):
        self.executed()

        coordinator = self.make_coordinator()
        result = coordinator.handle_command(self.command)

        self.assertEqual(result, 4)
        self.assertEqual(
            self.journal.get(self.command.command_id)["state"],
            "acknowledged",
        )

        self.control.acknowledge.assert_called_once_with(
            "box-5",
            self.command.command_id,
            success=True,
            last_sequence=4,
            occurred_at=self.stopped_at,
        )

        self.controller.stop_capture.assert_not_called()

    def test_recupera_confirmacion_perdida(self):
        self.executed(last_sequence=2)

        self.control.acknowledge.side_effect = [
            TimeoutError("Respuesta perdida"),
            Mock(),
        ]

        first = self.make_coordinator()

        with self.assertRaises(TimeoutError):
            first.handle_command(self.command)

        restarted = self.make_coordinator()
        result = restarted.handle_command(self.command)

        self.assertEqual(result, 2)
        self.assertEqual(
            self.control.acknowledge.call_count,
            2,
        )

        calls = self.control.acknowledge.call_args_list

        self.assertEqual(
            calls[0].kwargs["occurred_at"],
            calls[1].kwargs["occurred_at"],
        )

        self.controller.stop_capture.assert_not_called()

    def test_no_repite_detencion_confirmada(self):
        self.executed(last_sequence=-1)
        self.journal.mark_acknowledged(self.command)

        coordinator = self.make_coordinator()
        result = coordinator.handle_command(self.command)

        self.assertEqual(result, -1)

        self.control.acknowledge.assert_not_called()
        self.controller.connect.assert_not_called()
        self.controller.stop_capture.assert_not_called()

    def test_no_confirma_si_obs_continua_activo(self):
        self.executed()

        self.controller.status.return_value = {
            "recording": True,
            "streaming": True,
        }

        coordinator = self.make_coordinator()

        with self.assertRaises(RuntimeError):
            coordinator.handle_command(self.command)

        self.control.acknowledge.assert_not_called()
        self.controller.stop_capture.assert_not_called()


if __name__ == "__main__":
    unittest.main()
