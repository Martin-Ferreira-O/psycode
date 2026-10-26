import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from backend.apps.capture.domain import Command

from .session_coordinator import SessionCoordinator


class StartAcknowledgementRecoveryTests(unittest.TestCase):

    def test_no_reinicia_obs_si_se_pierde_confirmacion(self):
        config = SimpleNamespace(box_id="box-5")
        control = Mock()
        controller = Mock()
        runner = Mock()
        runner.store.last_sequence.return_value = -1

        # Primer intento: se pierde la respuesta.
        # Segundo intento: confirmacion exitosa.
        control.acknowledge.side_effect = [
            TimeoutError("Respuesta perdida"),
            SimpleNamespace(state="activa"),
        ]

        coordinator = SessionCoordinator(
            config=config,
            control=control,
            controller=controller,
            runner_factory=lambda cfg: runner,
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

        with self.assertRaises(TimeoutError):
            coordinator.handle_command(command)

        # La misma orden vuelve a entregarse.
        coordinator.handle_command(command)

        # No debe volver a ejecutar fisicamente el inicio.
        controller.start_capture.assert_called_once()

        # Ambos intentos deben conservar el mismo instante real.
        calls = control.acknowledge.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            calls[0].kwargs["occurred_at"],
            calls[1].kwargs["occurred_at"],
        )


if __name__ == "__main__":
    unittest.main()
