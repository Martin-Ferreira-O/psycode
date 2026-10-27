import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from backend.apps.capture.domain import Command

from .command_journal import CommandJournal
from .session_coordinator import SessionCoordinator


class RecoveryInspectionTests(unittest.TestCase):

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
            kind="inicio",
            scheduled_start=now - timedelta(minutes=1),
            scheduled_end=now + timedelta(hours=1),
        )

        self.coordinator = SessionCoordinator(
            config=self.config,
            control=self.control,
            controller=self.controller,
            journal=self.journal,
        )

    def test_detecta_obs_activo_con_orden_ejecutada(self):
        self.journal.prepare(self.command)
        self.journal.mark_executed(
            self.command,
            occurred_at=datetime.now(timezone.utc),
        )

        self.controller.status.return_value = {
            "recording": True,
            "streaming": True,
        }

        result = self.coordinator.inspect_recovery(self.command)

        self.assertEqual(result["journal_state"], "executed")
        self.assertTrue(result["recording"])
        self.assertTrue(result["streaming"])
        self.assertTrue(result["requires_reconciliation"])

        self.controller.start_capture.assert_not_called()
        self.controller.stop_capture.assert_not_called()
        self.controller.disconnect.assert_called_once()

    def test_detecta_orden_preparada_con_obs_detenido(self):
        self.journal.prepare(self.command)

        self.controller.status.return_value = {
            "recording": False,
            "streaming": False,
        }

        result = self.coordinator.inspect_recovery(self.command)

        self.assertEqual(result["journal_state"], "prepared")
        self.assertFalse(result["recording"])
        self.assertFalse(result["streaming"])

        self.controller.start_capture.assert_not_called()
        self.controller.stop_capture.assert_not_called()

    def test_no_conecta_obs_si_no_existe_la_orden(self):
        result = self.coordinator.inspect_recovery(self.command)

        self.assertIsNone(result)
        self.controller.connect.assert_not_called()

    def test_desconecta_obs_si_falla_la_consulta(self):
        self.journal.prepare(self.command)
        self.controller.status.side_effect = ConnectionError(
            "OBS no disponible"
        )

        with self.assertRaises(ConnectionError):
            self.coordinator.inspect_recovery(self.command)

        self.controller.disconnect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
