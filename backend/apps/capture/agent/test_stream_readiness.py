import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from backend.apps.capture.domain import Command

from .obs_controller import OBSController
from .session_coordinator import SessionCoordinator


class StreamReadinessTests(unittest.TestCase):

    def setUp(self):
        self.config = SimpleNamespace(
            box_id="box-5",
            stream_url="rtsp://127.0.0.1:8554/sala1",
        )
        self.controller = OBSController(self.config)

    @patch("backend.apps.capture.agent.obs_controller.subprocess.run")
    def test_espera_hasta_que_hay_audio(self, run):
        run.side_effect = [
            subprocess.CompletedProcess([], 1, "", ""),
            subprocess.CompletedProcess([], 0, "audio\n", ""),
        ]

        self.controller.wait_for_audio_stream(
            timeout=2,
            retry_interval=0.01,
        )

        self.assertEqual(run.call_count, 2)

    @patch("backend.apps.capture.agent.obs_controller.subprocess.run")
    def test_falla_si_audio_no_aparece(self, run):
        run.return_value = subprocess.CompletedProcess(
            [], 1, "", ""
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "AGENT_STREAM_NOT_READY",
        ):
            self.controller.wait_for_audio_stream(
                timeout=0.05,
                retry_interval=0.01,
            )

        self.assertGreaterEqual(run.call_count, 1)

    @patch("backend.apps.capture.agent.obs_controller.subprocess.run")
    def test_detecta_ffprobe_no_instalado(self, run):
        run.side_effect = FileNotFoundError()

        with self.assertRaisesRegex(
            RuntimeError,
            "AGENT_FFPROBE_UNAVAILABLE",
        ):
            self.controller.wait_for_audio_stream()

    def test_rechaza_intervalos_invalidos(self):
        with self.assertRaises(ValueError):
            self.controller.wait_for_audio_stream(timeout=0)


class CoordinatorStreamReadinessTests(unittest.TestCase):

    def test_fallo_rtsp_revierte_obs_y_rechaza_inicio(self):
        config = SimpleNamespace(box_id="box-5")
        control = Mock()
        controller = Mock()

        controller.wait_for_audio_stream.side_effect = RuntimeError(
            "AGENT_STREAM_NOT_READY"
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

        coordinator = SessionCoordinator(
            config=config,
            control=control,
            controller=controller,
            runner_factory=Mock(),
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "AGENT_STREAM_NOT_READY",
        ):
            coordinator.handle_command(command)

        controller.start_capture.assert_called_once()
        controller.wait_for_audio_stream.assert_called_once()
        controller.stop_capture.assert_called_once()
        controller.disconnect.assert_called_once()

        self.assertIsNone(coordinator.session_id)
        self.assertIsNone(coordinator.thread)

        self.assertEqual(
            control.acknowledge.call_args.kwargs["error_code"],
            "AGENT_START_FAILED",
        )


if __name__ == "__main__":
    unittest.main()
