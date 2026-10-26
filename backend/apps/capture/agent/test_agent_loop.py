import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from .agent_loop import AgentLoop


class AgentLoopTests(unittest.TestCase):

    def setUp(self):
        self.config = SimpleNamespace(
            box_id="box-5",
            command_poll_interval=5.0,
            heartbeat_interval=30.0,
        )

        self.control = Mock()
        self.coordinator = Mock()
        self.coordinator.session_id = None

        self.now = [100.0]

        self.loop = AgentLoop(
            config=self.config,
            control=self.control,
            coordinator=self.coordinator,
            clock=lambda: self.now[0],
        )

    def test_consulta_ordenes_del_box(self):
        self.control.commands.return_value = ()

        self.loop.tick()

        self.control.commands.assert_called_once_with("box-5")
        self.coordinator.heartbeat.assert_not_called()

    def test_heartbeat_periodico(self):
        session_id = uuid4()
        self.coordinator.session_id = session_id
        self.control.commands.return_value = ()

        # Primer heartbeat.
        self.loop.tick()

        self.now[0] = 110.0
        self.loop.tick()

        self.now[0] = 131.0
        self.loop.tick()

        self.assertEqual(
            self.coordinator.heartbeat.call_count,
            2,
        )

    def test_inicio_y_detencion(self):
        session_id = uuid4()

        start = SimpleNamespace(kind="inicio")
        stop = SimpleNamespace(kind="detencion")

        self.control.commands.side_effect = [
            (start,),
            (stop,),
        ]

        def execute(command):
            if command.kind == "inicio":
                self.coordinator.session_id = session_id
            elif command.kind == "detencion":
                self.coordinator.session_id = None

        self.coordinator.handle_command.side_effect = execute

        self.loop.tick()
        self.coordinator.heartbeat.assert_called_once()

        self.now[0] = 110.0
        self.loop.tick()

        self.assertEqual(
            self.coordinator.handle_command.call_count,
            2,
        )

        # No debe informar actividad tras la detencion.
        self.coordinator.heartbeat.assert_called_once()

    def test_intervalos_invalidos(self):
        self.config.heartbeat_interval = 0

        with self.assertRaises(ValueError):
            AgentLoop(
                config=self.config,
                control=self.control,
                coordinator=self.coordinator,
            )


if __name__ == "__main__":
    unittest.main()
