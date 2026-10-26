import unittest
from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from backend.apps.capture.domain import Command

from .session_coordinator import SessionCoordinator


class FailingRunner:
    """Simula una falla inmediata de FFmpeg."""

    def __init__(self):
        self.finished = Event()
        self.store = Mock()
        self.store.last_sequence.return_value = -1

    def run(self, session_id, captured_at_start, seconds=None):
        self.finished.set()
        raise RuntimeError("Fallo simulado de FFmpeg")

    def stop(self):
        self.finished.set()


class SessionCoordinatorFailureTests(unittest.TestCase):

    def test_reporta_interrupcion_automaticamente(self):
        config = SimpleNamespace(box_id="box-5")
        control = Mock()
        controller = Mock()
        runner = FailingRunner()

        coordinator = SessionCoordinator(
            config=config,
            control=control,
            controller=controller,
            runner_factory=lambda config: runner,
        )

        now = datetime.now(timezone.utc)
        session_id = uuid4()

        command = Command(
            command_id=uuid4(),
            session_id=session_id,
            box="box-5",
            kind="inicio",
            scheduled_start=now - timedelta(minutes=1),
            scheduled_end=now + timedelta(hours=1),
        )

        coordinator.handle_command(command)

        self.assertTrue(runner.finished.wait(timeout=2))
        coordinator.thread.join(timeout=2)

        self.assertIsNotNone(coordinator.capture_error)

        # El fallo debe notificarse sin llamar manualmente a heartbeat.
        control.interrupted.assert_called_once_with(
            "box-5",
            session_id,
            error_code="AGENT_INTERRUPTED",
        )


if __name__ == "__main__":
    unittest.main()
