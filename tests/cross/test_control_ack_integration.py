"""Respuestas perdidas después de guardar el ACK en SCRUM-71."""
import tempfile
from dataclasses import replace, asdict
from psycode_agent.domain import Command
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import TestCase

from backend.apps.capture.models import CaptureSession
from backend.apps.capture.tests import CaptureFixtures, NOW
from psycode_agent.agent_loop import AgentLoop
from psycode_agent.command_journal import CommandJournal
from psycode_agent.session_coordinator import SessionCoordinator, StopCaptureError


class ControlAcknowledgementTests(CaptureFixtures, TestCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.session = self.create()
        self.now = NOW + timedelta(seconds=1)
        self.lose_response = False
        config = SimpleNamespace(
            box_id="box-3", control_tick_interval=1, heartbeat_interval=30,
        )
        self.control = Mock()
        self.control.commands.side_effect = lambda box: tuple(Command(**asdict(c)) for c in self.service.commands(box, now=self.now))
        self.control.acknowledge.side_effect = self.acknowledge
        self.control.heartbeat.side_effect = lambda box, session: self.service.heartbeat(
            box, session, now=self.now,
        )
        self.runner = Mock()
        self.runner.store.recover_session.return_value = {}
        self.runner.store.last_sequence.return_value = -1
        self.coordinator = SessionCoordinator(
            config, self.control,
            runner_factory=lambda cfg: self.runner,
            journal=CommandJournal(temporary.name, "box-3"),
        )
        self.coordinator._now = lambda: self.now
        self.loop = AgentLoop(config, self.control, coordinator=self.coordinator)

    def acknowledge(self, box, command_id, **kwargs):
        result = self.service.acknowledge(box, command_id, now=self.now, **kwargs)
        if self.lose_response:
            self.lose_response = False
            raise TimeoutError("Respuesta perdida después del commit")
        return result

    def test_inicio_recupera_ack_sin_reentrega_del_backend(self):
        self.lose_response = True
        with self.assertRaises(TimeoutError):
            self.loop.tick()
        self.assertEqual(self.service.commands("box-3", now=self.now), ())

        self.loop.tick()
        self.coordinator.thread.join(timeout=1)

        self.assertEqual(self.coordinator.session_id, self.session.session_id)
        self.runner.run.assert_called_once()
        calls = self.control.acknowledge.call_args_list
        self.assertEqual(calls[0], calls[1])

    def test_detencion_recupera_ack_sin_reentrega_del_backend(self):
        self.loop.tick()
        self.coordinator.thread.join(timeout=1)
        self.now = NOW + timedelta(seconds=30)
        self.service.apply_authorization(
            replace(self.authorization, authorized=False, inicio=None, termino=None),
            now=self.now,
        )
        self.lose_response = True
        with self.assertRaises(TimeoutError):
            self.loop.tick()
        self.assertEqual(self.service.commands("box-3", now=self.now), ())

        self.loop.tick()

        self.assertIsNone(self.coordinator.session_id)
        self.assertEqual(CaptureSession.objects.get().state, "completada")
        self.runner.stop.assert_called_once()
        calls = self.control.acknowledge.call_args_list
        self.assertEqual(calls[-2], calls[-1])

    def test_reintenta_detencion_fallida_con_journal_y_backend_reales(self):
        self.loop.tick()
        self.coordinator.thread.join(timeout=1)
        self.now = NOW + timedelta(seconds=30)
        self.service.apply_authorization(
            replace(self.authorization, authorized=False, inicio=None, termino=None),
            now=self.now,
        )
        self.runner.stop.side_effect = [RuntimeError("micrófono ocupado"),
                                                   RuntimeError("micrófono ocupado"), None]

        for _ in range(2):
            with self.assertRaises(StopCaptureError):
                self.loop.tick()
            self.now += timedelta(seconds=1)
        self.loop.tick()

        self.assertIsNone(self.coordinator.session_id)
        self.assertEqual(self.runner.stop.call_count, 3)
        stop, = [record for record in self.coordinator.journal.root.glob("*.json")
                 if self.coordinator.journal.get(record.stem)["kind"] == "detencion"]
        self.assertEqual(self.coordinator.journal.get(stop.stem)["state"], "acknowledged")
