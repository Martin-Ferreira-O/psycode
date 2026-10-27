import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from backend.apps.capture.domain import Command

from .command_journal import CommandJournal
from .session_coordinator import SessionCoordinator


class SessionCoordinatorJournalTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.config = SimpleNamespace(box_id="box-5")
        self.control = Mock()
        self.controller = Mock()
        self.runner = Mock()

        self.journal = CommandJournal(
            self.temp.name,
            "box-5",
        )

        now = datetime.now(timezone.utc)

        self.command = Command(
            command_id=uuid4(),
            session_id=uuid4(),
            box="box-5",
            kind="inicio",
            scheduled_start=now - timedelta(minutes=1),
            scheduled_end=now + timedelta(hours=1),
        )

    def make_coordinator(self):
        return SessionCoordinator(
            config=self.config,
            control=self.control,
            controller=self.controller,
            runner_factory=lambda config: self.runner,
            journal=self.journal,
        )

    def test_inicio_confirmado_queda_persistido(self):
        coordinator = self.make_coordinator()

        coordinator.handle_command(self.command)
        coordinator.thread.join(timeout=2)

        saved = self.journal.get(self.command.command_id)

        self.assertEqual(saved["state"], "acknowledged")
        self.assertEqual(
            saved["session_id"],
            str(self.command.session_id),
        )

    def test_confirmacion_perdida_conserva_ejecucion(self):
        self.control.acknowledge.side_effect = TimeoutError(
            "Respuesta perdida"
        )

        coordinator = self.make_coordinator()

        with self.assertRaises(TimeoutError):
            coordinator.handle_command(self.command)

        saved = self.journal.get(self.command.command_id)

        self.assertEqual(saved["state"], "executed")
        self.assertIsNotNone(saved["occurred_at"])

        # Simula reconstruir el almacenamiento.
        restarted = CommandJournal(
            self.temp.name,
            "box-5",
        )

        recovered = restarted.get(self.command.command_id)

        self.assertEqual(
            recovered["occurred_at"],
            saved["occurred_at"],
        )

        self.controller.start_capture.assert_called_once()


if __name__ == "__main__":
    unittest.main()
