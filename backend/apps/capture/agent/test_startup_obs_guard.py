import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from backend.apps.capture.domain import Command

from .agent_loop import AgentLoop


class StartupOBSGuardTests(unittest.TestCase):

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
        self.loop = AgentLoop(self.config, self.control)

        self.obs = Mock()
        self.obs.status.return_value = {
            "recording": False,
            "streaming": False,
        }
        self.loop.coordinator.controller = self.obs

    def test_obs_detenido_permite_arranque(self):
        self.assertEqual(
            self.loop.check_startup_recovery(),
            [],
        )

        self.obs.connect.assert_called_once()
        self.obs.status.assert_called_once()
        self.obs.disconnect.assert_called_once()

    def test_streaming_activo_bloquea_arranque(self):
        self.obs.status.return_value = {
            "recording": False,
            "streaming": True,
        }

        with self.assertRaisesRegex(
            RuntimeError,
            "AGENT_OBS_BUSY_STARTUP",
        ):
            self.loop.run(stop_event=threading.Event())

        self.control.commands.assert_not_called()
        self.obs.stop_capture.assert_not_called()
        self.obs.disconnect.assert_called_once()

    def test_grabacion_activa_bloquea_arranque(self):
        self.obs.status.return_value = {
            "recording": True,
            "streaming": False,
        }

        with self.assertRaisesRegex(
            RuntimeError,
            "AGENT_OBS_BUSY_STARTUP",
        ):
            self.loop.check_startup_recovery()

        self.obs.stop_capture.assert_not_called()

    def test_obs_inaccesible_bloquea_arranque(self):
        self.obs.status.side_effect = ConnectionError(
            "OBS no disponible"
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "AGENT_OBS_STATUS_UNAVAILABLE",
        ):
            self.loop.check_startup_recovery()

        self.obs.disconnect.assert_called_once()
        self.control.commands.assert_not_called()

    def test_journal_pendiente_bloquea_antes_de_obs(self):
        now = datetime.now(timezone.utc)

        command = Command(
            command_id=uuid4(),
            session_id=uuid4(),
            box="box-5",
            kind="inicio",
            scheduled_start=now - timedelta(minutes=1),
            scheduled_end=now + timedelta(hours=1),
        )

        self.loop.coordinator.journal.prepare(command)

        with self.assertRaisesRegex(
            RuntimeError,
            "AGENT_RECOVERY_REQUIRED",
        ):
            self.loop.check_startup_recovery()

        self.obs.connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
