import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import httpx

from .agent_loop import AgentLoop
from .session_coordinator import StopCaptureError


class FakeStopEvent:
    """Permite probar el ciclo sin esperas reales."""

    def __init__(self, stop_after):
        self.stop_after = stop_after
        self.wait_count = 0
        self.waits = []

    def is_set(self):
        return self.wait_count >= self.stop_after

    def wait(self, seconds):
        self.waits.append(seconds)
        self.wait_count += 1


class AgentLoopRecoveryTests(unittest.TestCase):

    def setUp(self):
        self.config = SimpleNamespace(
            box_id="box-5",
            command_poll_interval=5.0,
            heartbeat_interval=30.0,
            control_max_failures=3,
        )

        self.control = Mock()
        self.coordinator = Mock()
        self.coordinator.session_id = None

        self.loop = AgentLoop(
            config=self.config,
            control=self.control,
            coordinator=self.coordinator,
        )

    def test_recupera_conexion_sin_repetir_orden(self):
        command = object()

        self.control.commands.side_effect = [
            TimeoutError("Timeout temporal"),
            httpx.ConnectError("Conexion rechazada"),
            (command,),
        ]

        stop_event = FakeStopEvent(stop_after=3)

        self.loop.run(stop_event=stop_event)

        self.assertEqual(self.control.commands.call_count, 3)

        # La orden se ejecuta solo cuando realmente llega.
        self.coordinator.handle_command.assert_called_once_with(
            command
        )

        self.assertEqual(
            stop_event.waits,
            [5.0, 5.0, 5.0],
        )

    def test_agota_reintentos(self):
        self.control.commands.side_effect = TimeoutError(
            "Backend sin respuesta"
        )

        stop_event = FakeStopEvent(stop_after=10)

        with self.assertRaisesRegex(
            RuntimeError,
            "agotar los reintentos",
        ):
            self.loop.run(stop_event=stop_event)

        self.assertEqual(
            self.control.commands.call_count,
            3,
        )

        self.assertEqual(
            len(stop_event.waits),
            2,
        )

    def test_error_de_programacion_no_se_reintenta(self):
        self.control.commands.side_effect = ValueError(
            "Respuesta invalida"
        )

        stop_event = FakeStopEvent(stop_after=10)

        with self.assertRaises(ValueError):
            self.loop.run(stop_event=stop_event)

        self.control.commands.assert_called_once()

    def test_reintenta_fallo_de_detencion_sin_abandonar_el_bucle(self):
        self.control.commands.return_value = (object(),)
        self.coordinator.handle_command.side_effect = [StopCaptureError("OBS ocupado"), None]
        self.loop.run(stop_event=FakeStopEvent(stop_after=2))
        self.assertEqual(self.coordinator.handle_command.call_count, 2)

    def test_limita_reintentos_de_detencion(self):
        self.control.commands.return_value = (object(),)
        self.coordinator.handle_command.side_effect = StopCaptureError("OBS ocupado")
        with self.assertRaises(StopCaptureError):
            self.loop.run(stop_event=FakeStopEvent(stop_after=10))
        self.assertEqual(self.coordinator.handle_command.call_count, 3)


if __name__ == "__main__":
    unittest.main()
