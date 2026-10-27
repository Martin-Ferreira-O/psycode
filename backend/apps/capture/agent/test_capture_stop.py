
import threading
import subprocess
import unittest

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from .audio_chunker import capture_audio


class FakeStdout:
    """Simula audio y luego una lectura bloqueada."""

    def __init__(self):
        self.read_count = 0
        self.terminated = threading.Event()
        self.closed = False

    def read(self, size):
        if self.read_count < 10:
            self.read_count += 1
            return b"\x00" * size

        self.terminated.wait(timeout=3)
        return b""

    def close(self):
        self.closed = True


class FakeProcess:
    """Simula un proceso FFmpeg controlable."""

    def __init__(self):
        self.stdout = FakeStdout()
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15
        self.stdout.terminated.set()

    def wait(self, timeout=None):
        if not self.stdout.terminated.wait(timeout=timeout or 3):
            raise subprocess.TimeoutExpired("ffmpeg", timeout)
        return self.returncode


class CaptureStopTests(unittest.TestCase):

    def setUp(self):
        self.config = SimpleNamespace(
            box_id="box-5",
            stream_url="rtsp://127.0.0.1/test",
            chunk_duration=10,
            chunk_overlap=1,
        )

    def test_stop_event_detiene_ffmpeg(self):
        stop_event = threading.Event()
        fragment_created = threading.Event()

        process = FakeProcess()
        sequences = []
        errors = []

        def fake_save_fragment(**kwargs):
            sequence = kwargs["sequence"]
            sequences.append(sequence)
            fragment_created.set()

            return {
                "sequence": sequence,
                "box": kwargs["box"],
                "session_id": str(kwargs["session_id"]),
            }

        def run_capture():
            try:
                capture_audio(
                    config=self.config,
                    seconds=60,
                    session_id=uuid4(),
                    captured_at_start=datetime.now(
                        timezone.utc
                    ),
                    stop_event=stop_event,
                )
            except Exception as exc:
                errors.append(exc)

        with (
            patch(
                "backend.apps.capture.agent.audio_chunker.subprocess.Popen",
                return_value=process,
            ),
            patch(
                "backend.apps.capture.agent.audio_chunker.save_fragment",
                side_effect=fake_save_fragment,
            ),
        ):
            capture_thread = threading.Thread(
                target=run_capture,
                daemon=True,
            )

            capture_thread.start()

            try:
                self.assertTrue(
                    fragment_created.wait(timeout=3),
                    "No se generó el primer fragmento",
                )
            finally:
                stop_event.set()
                capture_thread.join(timeout=5)

        self.assertFalse(
            capture_thread.is_alive(),
            "La captura no terminó",
        )

        self.assertEqual(errors, [])
        self.assertEqual(sequences, [0])
        self.assertEqual(process.returncode, -15)
        self.assertTrue(process.stdout.closed)

    def test_captura_continua_hasta_stop_event(self):
        """El modo continuo no fija duración."""

        stop_event = threading.Event()
        fragment_created = threading.Event()

        process = FakeProcess()
        sequences = []
        errors = []

        def fake_save_fragment(**kwargs):
            sequence = kwargs["sequence"]
            sequences.append(sequence)
            fragment_created.set()

            return {
                "sequence": sequence,
                "box": kwargs["box"],
                "session_id": str(kwargs["session_id"]),
            }

        def run_capture():
            try:
                capture_audio(
                    config=self.config,
                    seconds=None,
                    session_id=uuid4(),
                    captured_at_start=datetime.now(
                        timezone.utc
                    ),
                    stop_event=stop_event,
                )
            except Exception as exc:
                errors.append(exc)

        with (
            patch(
                "backend.apps.capture.agent.audio_chunker.subprocess.Popen",
                return_value=process,
            ) as mocked_popen,
            patch(
                "backend.apps.capture.agent.audio_chunker.save_fragment",
                side_effect=fake_save_fragment,
            ),
        ):
            capture_thread = threading.Thread(
                target=run_capture,
                daemon=True,
            )

            capture_thread.start()

            try:
                self.assertTrue(
                    fragment_created.wait(timeout=3),
                    "No se generó ningún fragmento",
                )
            finally:
                stop_event.set()
                capture_thread.join(timeout=5)

        self.assertFalse(capture_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(sequences, [0])

        command = mocked_popen.call_args.args[0]

        # En modo continuo FFmpeg no usa -t.
        self.assertNotIn("-t", command)

        self.assertEqual(process.returncode, -15)
        self.assertTrue(process.stdout.closed)

    def test_callback_notifica_fragmento_guardado(self):
        """Notifica el fragmento después de guardarlo."""

        stop_event = threading.Event()
        fragment_created = threading.Event()

        process = FakeProcess()

        saved_sequences = []
        notifications = []
        errors = []

        def fake_save_fragment(**kwargs):
            sequence = kwargs["sequence"]
            saved_sequences.append(sequence)

            return {
                "sequence": sequence,
                "box": kwargs["box"],
                "session_id": str(kwargs["session_id"]),
            }

        def on_fragment_saved(metadata):
            notifications.append(metadata)
            fragment_created.set()

        def run_capture():
            try:
                capture_audio(
                    config=self.config,
                    seconds=None,
                    session_id=uuid4(),
                    captured_at_start=datetime.now(
                        timezone.utc
                    ),
                    stop_event=stop_event,
                    on_fragment_saved=on_fragment_saved,
                )
            except Exception as exc:
                errors.append(exc)

        with (
            patch(
                "backend.apps.capture.agent.audio_chunker.subprocess.Popen",
                return_value=process,
            ),
            patch(
                "backend.apps.capture.agent.audio_chunker.save_fragment",
                side_effect=fake_save_fragment,
            ),
        ):
            capture_thread = threading.Thread(
                target=run_capture,
                daemon=True,
            )

            capture_thread.start()

            try:
                self.assertTrue(
                    fragment_created.wait(timeout=3),
                    "No se recibió la notificación",
                )
            finally:
                stop_event.set()
                capture_thread.join(timeout=5)

        self.assertFalse(capture_thread.is_alive())
        self.assertEqual(errors, [])

        # El fragmento se guarda una sola vez.
        self.assertEqual(saved_sequences, [0])

        # El callback recibe sus metadatos.
        self.assertEqual(len(notifications), 1)
        self.assertEqual(
            notifications[0]["sequence"],
            0,
        )
        self.assertEqual(
            notifications[0]["box"],
            "box-5",
        )

    def test_stop_mata_ffmpeg_si_ignora_terminate(self):
        class StubbornProcess(FakeProcess):
            def terminate(self):
                pass

            def kill(self):
                self.returncode = -9
                self.stdout.terminated.set()

        process = StubbornProcess()
        stopped = threading.Event()
        with (
            patch("backend.apps.capture.agent.audio_chunker.subprocess.Popen", return_value=process),
            patch("backend.apps.capture.agent.audio_chunker.FFMPEG_STOP_TIMEOUT", 0.01),
            patch("backend.apps.capture.agent.audio_chunker.save_fragment", return_value={}),
        ):
            capture_audio(
                self.config, None, uuid4(), datetime.now(timezone.utc),
                stop_event=stopped,
                on_fragment_saved=lambda metadata: stopped.set(),
            )

        self.assertEqual(process.returncode, -9)
        self.assertTrue(process.stdout.closed)


if __name__ == "__main__":
    unittest.main()
