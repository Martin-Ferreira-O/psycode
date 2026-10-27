import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from backend.apps.capture.domain import Command

from .command_journal import CommandJournal
from .session_coordinator import SessionCoordinator


class StopRecoveryTests(unittest.TestCase):

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

    def mark_executed(self, last_sequence=7):
        self.journal.mark_executed(
            self.command,
            occurred_at=self.stopped_at,
            last_sequence=last_sequence,
        )

    def test_recupera_detencion_sin_repetir_obs(self):
        self.mark_executed()

        coordinator = self.make_coordinator()
        result = coordinator.recover_stop_confirmation(self.command)

        self.assertEqual(result, 7)
        self.assertEqual(
            self.journal.get(self.command.command_id)["state"],
            "acknowledged",
        )

        self.control.acknowledge.assert_called_once_with(
            "box-5",
            self.command.command_id,
            success=True,
            last_sequence=7,
            occurred_at=self.stopped_at,
        )

        self.controller.start_capture.assert_not_called()
        self.controller.stop_capture.assert_not_called()

    def test_no_confirma_si_obs_sigue_activo(self):
        self.mark_executed()

        self.controller.status.return_value = {
            "recording": True,
            "streaming": True,
        }

        coordinator = self.make_coordinator()

        with self.assertRaises(RuntimeError):
            coordinator.recover_stop_confirmation(self.command)

        self.control.acknowledge.assert_not_called()

        self.assertEqual(
            self.journal.get(self.command.command_id)["state"],
            "executed",
        )

    def test_conserva_ejecucion_si_falla_backend(self):
        self.mark_executed(last_sequence=3)

        self.control.acknowledge.side_effect = TimeoutError(
            "Backend sin respuesta"
        )

        coordinator = self.make_coordinator()

        with self.assertRaises(TimeoutError):
            coordinator.recover_stop_confirmation(self.command)

        self.assertEqual(
            self.journal.get(self.command.command_id)["state"],
            "executed",
        )

        # Reintentar con un coordinador nuevo.
        self.control.acknowledge.side_effect = None

        restarted = self.make_coordinator()
        result = restarted.recover_stop_confirmation(self.command)

        self.assertEqual(result, 3)
        self.assertEqual(
            self.journal.get(self.command.command_id)["state"],
            "acknowledged",
        )

        calls = self.control.acknowledge.call_args_list

        self.assertEqual(len(calls), 2)
        self.assertEqual(
            calls[0].kwargs["occurred_at"],
            calls[1].kwargs["occurred_at"],
        )

    def test_no_confirma_orden_solo_preparada(self):
        coordinator = self.make_coordinator()

        with self.assertRaises(RuntimeError):
            coordinator.recover_stop_confirmation(self.command)

        self.control.acknowledge.assert_not_called()
        self.controller.stop_capture.assert_not_called()

    def test_detencion_ya_confirmada_no_se_repite(self):
        self.mark_executed(last_sequence=-1)
        self.journal.mark_acknowledged(self.command)

        coordinator = self.make_coordinator()
        result = coordinator.recover_stop_confirmation(self.command)

        self.assertEqual(result, -1)
        self.control.acknowledge.assert_not_called()
        self.controller.connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
