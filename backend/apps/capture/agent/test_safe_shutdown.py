import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from .agent_loop import AgentLoop
from .session_coordinator import SessionCoordinator


class SafeShutdownTests(unittest.TestCase):

    def setUp(self):
        self.config = SimpleNamespace(
            box_id="box-5",
            command_poll_interval=0.01,
            heartbeat_interval=30,
            control_max_failures=2,
        )

        self.control = Mock()
        self.controller = Mock()

        self.coordinator = SessionCoordinator(
            config=self.config,
            control=self.control,
            controller=self.controller,
            stop_timeout=3,
        )

    def activate_session(self):
        self.coordinator.session_id = uuid4()
        self.coordinator.runner = Mock()
        self.coordinator.thread = Mock()
        self.coordinator.thread.is_alive.side_effect = [
            True,
            False,
        ]

    def test_detiene_runner_antes_de_obs(self):
        self.activate_session()

        operations = Mock()
        operations.attach_mock(
            self.coordinator.runner.stop,
            "runner_stop",
        )
        operations.attach_mock(
            self.coordinator.thread.join,
            "thread_join",
        )
        operations.attach_mock(
            self.controller.stop_capture,
            "obs_stop",
        )

        self.coordinator.shutdown_after_control_failure()

        self.assertEqual(
            [call[0] for call in operations.mock_calls],
            ["runner_stop", "thread_join", "obs_stop"],
        )

        self.coordinator.thread.join.assert_called_once_with(
            timeout=3
        )
        self.controller.disconnect.assert_called_once()

    def test_timeout_del_hilo_intenta_detener_obs(self):
        self.activate_session()
        self.coordinator.thread.is_alive.side_effect = [
            True,
            True,
        ]

        with self.assertRaisesRegex(
            RuntimeError,
            "AGENT_CAPTURE_STOP_TIMEOUT",
        ):
            self.coordinator.shutdown_after_control_failure()

        self.controller.stop_capture.assert_called_once()
        self.controller.disconnect.assert_called_once()

    def test_fallo_obs_cierra_conexion(self):
        self.activate_session()
        self.controller.stop_capture.side_effect = RuntimeError(
            "OBS no responde"
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "AGENT_OBS_STOP_FAILED",
        ):
            self.coordinator.shutdown_after_control_failure()

        self.controller.disconnect.assert_called_once()

    def test_inicio_pendiente_tambien_detiene_obs(self):
        self.coordinator._pending_start = (
            uuid4(),
            uuid4(),
            datetime.now(timezone.utc),
            Mock(),
        )

        self.coordinator.shutdown_after_control_failure()

        self.controller.stop_capture.assert_called_once()
        self.controller.disconnect.assert_called_once()

    def test_sin_sesion_no_modifica_obs(self):
        self.coordinator.shutdown_after_control_failure()

        self.controller.stop_capture.assert_not_called()
        self.controller.disconnect.assert_not_called()


class AgentLoopShutdownTests(unittest.TestCase):

    def test_agotar_reintentos_activa_cierre(self):
        config = SimpleNamespace(
            box_id="box-5",
            command_poll_interval=0.01,
            heartbeat_interval=30,
            control_max_failures=2,
        )

        control = Mock()
        control.commands.side_effect = TimeoutError(
            "Backend no disponible"
        )

        coordinator = Mock()
        coordinator.session_id = None

        loop = AgentLoop(
            config=config,
            control=control,
            coordinator=coordinator,
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "Transporte de control no disponible",
        ):
            loop.run()

        self.assertEqual(control.commands.call_count, 2)
        coordinator.shutdown_after_control_failure.assert_called_once()


if __name__ == "__main__":
    unittest.main()
