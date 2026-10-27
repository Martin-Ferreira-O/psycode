import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from backend.apps.capture.domain import Command

from .command_journal import CommandJournal


class CommandJournalTests(unittest.TestCase):

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

        self.root = Path(self.temporary.name)
        self.journal = CommandJournal(self.root, "box-5")

        now = datetime.now(timezone.utc)

        self.command = Command(
            command_id=uuid4(),
            session_id=uuid4(),
            box="box-5",
            kind="inicio",
            scheduled_start=now - timedelta(minutes=1),
            scheduled_end=now + timedelta(hours=1),
        )

    def test_recupera_orden_tras_reinicio(self):
        self.journal.prepare(self.command)

        # Simula crear el agente nuevamente.
        restarted = CommandJournal(self.root, "box-5")

        recovered = restarted.get(self.command.command_id)

        self.assertEqual(recovered["state"], "prepared")
        self.assertEqual(
            recovered["session_id"],
            str(self.command.session_id),
        )

    def test_recupera_ejecucion_sin_perder_fecha(self):
        started_at = datetime.now(timezone.utc)

        self.journal.prepare(self.command)
        self.journal.mark_executed(
            self.command,
            occurred_at=started_at,
        )

        restarted = CommandJournal(self.root, "box-5")
        recovered = restarted.get(self.command.command_id)

        self.assertEqual(recovered["state"], "executed")
        self.assertEqual(
            recovered["occurred_at"],
            started_at.isoformat(),
        )

        restarted.mark_acknowledged(self.command)

        another_restart = CommandJournal(self.root, "box-5")
        final = another_restart.get(self.command.command_id)

        self.assertEqual(final["state"], "acknowledged")

    def test_no_reemplaza_identidad_de_orden(self):
        self.journal.prepare(self.command)

        different = Command(
            command_id=self.command.command_id,
            session_id=uuid4(),
            box="box-5",
            kind="inicio",
            scheduled_start=self.command.scheduled_start,
            scheduled_end=self.command.scheduled_end,
        )

        with self.assertRaises(ValueError):
            self.journal.prepare(different)

    def test_detencion_con_ultima_secuencia(self):
        stop = Command(
            command_id=uuid4(),
            session_id=self.command.session_id,
            box="box-5",
            kind="detencion",
            scheduled_start=self.command.scheduled_start,
            scheduled_end=self.command.scheduled_end,
        )

        stopped_at = datetime.now(timezone.utc)

        self.journal.prepare(stop)
        self.journal.mark_executed(
            stop,
            occurred_at=stopped_at,
            last_sequence=-1,
        )

        restarted = CommandJournal(self.root, "box-5")
        recovered = restarted.get(stop.command_id)

        self.assertEqual(recovered["last_sequence"], -1)
        self.assertEqual(recovered["state"], "executed")

    def test_no_confirma_orden_sin_ejecutar(self):
        self.journal.prepare(self.command)

        with self.assertRaises(RuntimeError):
            self.journal.mark_acknowledged(self.command)


if __name__ == "__main__":
    unittest.main()
