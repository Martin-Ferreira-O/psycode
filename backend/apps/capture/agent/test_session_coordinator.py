import threading
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import ANY, Mock
from uuid import uuid4

from backend.apps.capture.domain import Command

from .session_coordinator import SessionCoordinator


class FakeRunner:
    """Simula captura continua sin FFmpeg ni audio real."""

    def __init__(self):
        self.started = threading.Event()
        self.finished = threading.Event()
        self.store = Mock()
        self.store.last_sequence.return_value = 3

    def run(self, session_id, captured_at_start, seconds=None):
        self.started.set()
        self.finished.wait(timeout=5)

    def stop(self):
        self.finished.set()


class SessionCoordinatorTests(unittest.TestCase):

    def setUp(self):
        self.config = SimpleNamespace(box_id="box-5")
        self.control = Mock()
        self.controller = Mock()
        self.runner = FakeRunner()

        self.coordinator = SessionCoordinator(
            config=self.config,
            control=self.control,
            controller=self.controller,
            runner_factory=lambda config: self.runner,
            stop_timeout=3,
        )

        self.session_id = uuid4()

    def tearDown(self):
        # Evitar dejar un hilo de prueba ejecutandose.
        self.runner.stop()

        thread = self.coordinator.thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=3)

    def command(self, kind, session_id=None, box="box-5"):
        now = datetime.now(timezone.utc)

        return Command(
            command_id=uuid4(),
            session_id=session_id or self.session_id,
            box=box,
            kind=kind,
            scheduled_start=now - timedelta(minutes=1),
            scheduled_end=now + timedelta(hours=1),
        )

    def test_inicio_y_detencion(self):
        start = self.command("inicio")

        result = self.coordinator.handle_command(start)

        self.assertEqual(result, self.session_id)
        self.assertTrue(self.runner.started.wait(timeout=2))

        self.controller.start_capture.assert_called_once()

        self.control.acknowledge.assert_any_call(
            "box-5",
            start.command_id,
            success=True,
            occurred_at=ANY,
        )

        stop = self.command("detencion")

        last_sequence = self.coordinator.handle_command(stop)

        self.assertEqual(last_sequence, 3)

        self.control.acknowledge.assert_any_call(
            "box-5",
            stop.command_id,
            success=True,
            last_sequence=3,
            occurred_at=ANY,
        )

        self.controller.stop_capture.assert_called_once()
        self.assertIsNone(self.coordinator.session_id)

    def test_no_repite_inicio(self):
        start = self.command("inicio")

        first = self.coordinator.handle_command(start)
        second = self.coordinator.handle_command(start)

        self.assertEqual(first, second)
        self.controller.start_capture.assert_called_once()

    def test_rechaza_orden_de_otro_box(self):
        start = self.command("inicio", box="box-3")

        with self.assertRaises(ValueError):
            self.coordinator.handle_command(start)

        self.controller.connect.assert_not_called()

    def test_rechaza_inicio_fuera_de_ventana(self):
        now = datetime.now(timezone.utc)

        start = Command(
            command_id=uuid4(),
            session_id=self.session_id,
            box="box-5",
            kind="inicio",
            scheduled_start=now - timedelta(hours=2),
            scheduled_end=now - timedelta(hours=1),
        )

        with self.assertRaises(RuntimeError):
            self.coordinator.handle_command(start)

        self.controller.start_capture.assert_not_called()

    def test_heartbeat(self):
        start = self.command("inicio")
        self.coordinator.handle_command(start)

        self.assertTrue(self.runner.started.wait(timeout=2))

        self.coordinator.heartbeat()

        self.control.heartbeat.assert_called_once_with(
            "box-5",
            self.session_id,
        )

    def test_no_detiene_otra_sesion(self):
        start = self.command("inicio")
        self.coordinator.handle_command(start)

        self.assertTrue(self.runner.started.wait(timeout=2))

        stop = self.command(
            "detencion",
            session_id=uuid4(),
        )

        with self.assertRaises(RuntimeError):
            self.coordinator.handle_command(stop)

        self.controller.stop_capture.assert_not_called()


if __name__ == "__main__":
    unittest.main()
