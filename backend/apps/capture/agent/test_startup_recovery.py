import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from backend.apps.capture.domain import Command

from .agent_loop import AgentLoop


class StartupRecoveryTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.config = SimpleNamespace(
            box_id="box-5",
            agent_state_root=self.temp.name,
            command_poll_interval=0.01,
            heartbeat_interval=30,
            control_max_failures=2,
        )

        self.control = Mock()

        self.loop = AgentLoop(
            config=self.config,
            control=self.control,
        )

        # Simular OBS detenido durante las pruebas.
        self.loop.coordinator.controller = Mock()
        self.loop.coordinator.controller.status.return_value = {
            "recording": False,
            "streaming": False,
        }

        self.journal = self.loop.coordinator.journal

        self.session_id = uuid4()
        self.now = datetime.now(timezone.utc)

    def command(self, kind):
        return Command(
            command_id=uuid4(),
            session_id=self.session_id,
            box="box-5",
            kind=kind,
            scheduled_start=self.now - timedelta(minutes=1),
            scheduled_end=self.now + timedelta(hours=1),
        )

    def executed(self, command, last_sequence=None):
        self.journal.prepare(command)
        self.journal.mark_executed(
            command,
            occurred_at=self.now,
            last_sequence=last_sequence,
        )

    def test_permite_arranque_sin_registros(self):
        self.assertEqual(
            self.loop.check_startup_recovery(),
            [],
        )

    def test_bloquea_inicio_ejecutado_sin_detencion(self):
        start = self.command("inicio")
        self.executed(start)

        with self.assertRaisesRegex(
            RuntimeError,
            "AGENT_RECOVERY_REQUIRED",
        ):
            self.loop.run(stop_event=threading.Event())

        self.control.commands.assert_not_called()

    def test_bloquea_inicio_preparado(self):
        start = self.command("inicio")
        self.journal.prepare(start)

        unresolved = self.journal.unresolved_sessions()

        self.assertEqual(len(unresolved), 1)
        self.assertEqual(
            unresolved[0]["state"],
            "prepared",
        )

    def test_permite_sesion_con_detencion_ejecutada(self):
        start = self.command("inicio")
        stop = self.command("detencion")

        self.executed(start)
        self.executed(stop, last_sequence=4)

        self.assertEqual(
            self.loop.check_startup_recovery(),
            [],
        )

        stopped = threading.Event()
        stopped.set()

        self.loop.run(stop_event=stopped)

    def test_bloquea_detencion_solo_preparada(self):
        start = self.command("inicio")
        stop = self.command("detencion")

        self.executed(start)
        self.journal.prepare(stop)

        unresolved = self.journal.unresolved_sessions()

        self.assertTrue(unresolved)

        with self.assertRaisesRegex(
            RuntimeError,
            "AGENT_RECOVERY_REQUIRED",
        ):
            self.loop.check_startup_recovery()

    def test_bloquea_registro_invalido(self):
        corrupted = self.journal.root / "archivo-invalido.json"
        corrupted.write_text(
            '{"state": "executed"}',
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "AGENT_JOURNAL_INVALID",
        ):
            self.loop.check_startup_recovery()


if __name__ == "__main__":
    unittest.main()
