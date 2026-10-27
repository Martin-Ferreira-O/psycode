import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from backend.apps.capture.domain import Command

from .command_journal import CommandJournal
from .session_coordinator import SessionCoordinator


class StopJournalTests(unittest.TestCase):

    def test_detencion_confirmada_queda_persistida(self):
        with tempfile.TemporaryDirectory() as directory:
            config = SimpleNamespace(box_id="box-5")
            control = Mock()
            controller = Mock()
            runner = Mock()
            runner.store.last_sequence.return_value = 3

            journal = CommandJournal(directory, "box-5")

            coordinator = SessionCoordinator(
                config=config,
                control=control,
                controller=controller,
                runner_factory=lambda cfg: runner,
                journal=journal,
            )

            now = datetime.now(timezone.utc)
            session_id = uuid4()

            start = Command(
                command_id=uuid4(),
                session_id=session_id,
                box="box-5",
                kind="inicio",
                scheduled_start=now - timedelta(minutes=1),
                scheduled_end=now + timedelta(hours=1),
            )

            stop = Command(
                command_id=uuid4(),
                session_id=session_id,
                box="box-5",
                kind="detencion",
                scheduled_start=start.scheduled_start,
                scheduled_end=start.scheduled_end,
            )

            coordinator.handle_command(start)
            coordinator.thread.join(timeout=2)

            coordinator.handle_command(stop)

            # La detencion debe persistir su secuencia final.
            restarted = CommandJournal(directory, "box-5")
            saved = restarted.get(stop.command_id)

            self.assertIsNotNone(saved)
            self.assertEqual(saved["state"], "acknowledged")
            self.assertEqual(saved["last_sequence"], 3)
            self.assertIsNotNone(saved["occurred_at"])


if __name__ == "__main__":
    unittest.main()
