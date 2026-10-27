import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from backend.apps.capture.domain import Command

from .agent_loop import AgentLoop
from .command_journal import CommandJournal


class AgentJournalSetupTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.config = SimpleNamespace(
            box_id="box-5",
            agent_state_root=self.temp.name,
            command_poll_interval=5.0,
            heartbeat_interval=30.0,
            control_max_failures=3,
        )

        self.control = Mock()

    def test_crea_journal_automaticamente(self):
        loop = AgentLoop(
            config=self.config,
            control=self.control,
        )

        journal = loop.coordinator.journal

        self.assertIsInstance(journal, CommandJournal)
        self.assertEqual(
            journal.root,
            Path(self.temp.name) / "box-5",
        )
        self.assertTrue(journal.root.is_dir())

    def test_conserva_orden_entre_instancias(self):
        first = AgentLoop(
            config=self.config,
            control=self.control,
        )

        now = datetime.now(timezone.utc)

        command = Command(
            command_id=uuid4(),
            session_id=uuid4(),
            box="box-5",
            kind="inicio",
            scheduled_start=now - timedelta(minutes=1),
            scheduled_end=now + timedelta(hours=1),
        )

        first.coordinator.journal.prepare(command)
        first.coordinator.journal.mark_executed(
            command,
            occurred_at=now,
        )

        restarted = AgentLoop(
            config=self.config,
            control=self.control,
        )

        saved = restarted.coordinator.journal.get(
            command.command_id
        )

        self.assertEqual(saved["state"], "executed")
        self.assertEqual(
            saved["session_id"],
            str(command.session_id),
        )
        self.assertEqual(
            saved["occurred_at"],
            now.isoformat(),
        )

    def test_rechaza_ruta_no_configurada(self):
        self.config.agent_state_root = ""

        with self.assertRaises(ValueError):
            AgentLoop(
                config=self.config,
                control=self.control,
            )


if __name__ == "__main__":
    unittest.main()
