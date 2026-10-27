
import hashlib
import subprocess
import tempfile
import threading
import time
import unittest

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from . import audio_chunker
from .backend_client import FragmentUploadError
from .capture_runner import CaptureRunner
from .fragment_store import FragmentStore


class FakeBackendClient:
    """Simula un backend que demora en aceptar el primer WAV."""

    def __init__(self):
        self.config = SimpleNamespace(box_id="box-5")
        self.first_upload_started = threading.Event()
        self.release_first_upload = threading.Event()
        self.first_upload_finished = threading.Event()
        self.uploaded_sequences = []

    def upload_fragment(
        self,
        file_path,
        session_id,
        sequence,
        captured_at,
        checksum,
    ):
        if sequence == 0:
            self.first_upload_started.set()

            if not self.release_first_upload.wait(timeout=15):
                raise FragmentUploadError(
                    "Timeout simulado en backend"
                )

        audio_path = Path(file_path)
        audio_bytes = audio_path.read_bytes()

        if hashlib.sha256(audio_bytes).hexdigest() != checksum:
            raise FragmentUploadError(
                "Checksum inválido"
            )

        self.uploaded_sequences.append(sequence)

        if sequence == 0:
            self.first_upload_finished.set()

        return {
            "estado": "aceptado",
            "box": "box-5",
            "session_id": session_id,
            "secuencia": sequence,
            "formato": "wav",
            "checksum": checksum,
            "size_bytes": len(audio_bytes),
        }


class FFmpegUploadIntegrationTests(unittest.TestCase):

    def test_captura_continua_durante_envio_lento(self):
        """FFmpeg sigue capturando mientras un envío espera."""

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fragments_root = root / "fragments"
            session_id = uuid4()

            # Fragmentos cortos únicamente para la prueba.
            config = SimpleNamespace(
                box_id="box-5",
                stream_url="rtsp://127.0.0.1/test",
                chunk_duration=2,
                chunk_overlap=0,
            )

            store = FragmentStore(fragments_root)
            client = FakeBackendClient()

            errors = []
            real_popen = subprocess.Popen

            def use_synthetic_audio(command, **kwargs):
                command = list(command)

                index = command.index("-rtsp_transport")
                del command[index:index + 2]

                index = command.index("-i")
                command[index:index + 2] = [
                    "-re",
                    "-f", "lavfi",
                    "-i",
                    "sine=frequency=440:sample_rate=16000",
                ]

                return real_popen(command, **kwargs)

            with (
                patch.object(
                    audio_chunker,
                    "__file__",
                    str(root / "audio_chunker.py"),
                ),
                patch.object(
                    audio_chunker.subprocess,
                    "Popen",
                    side_effect=use_synthetic_audio,
                ),
                patch(
                    "backend.apps.capture.agent.capture_runner.FragmentStore",
                    return_value=store,
                ),
                patch(
                    "backend.apps.capture.agent.capture_runner.BackendClient",
                    return_value=client,
                ),
            ):
                runner = CaptureRunner(config)

                def run_agent():
                    try:
                        runner.run(
                            session_id=session_id,
                            captured_at_start=datetime.now(
                                timezone.utc
                            ),
                            seconds=None,
                        )
                    except Exception as exc:
                        errors.append(exc)

                thread = threading.Thread(
                    target=run_agent,
                    daemon=True,
                )

                thread.start()

                try:
                    # El primer envío debe comenzar.
                    self.assertTrue(
                        client.first_upload_started.wait(timeout=8),
                        "El primer envío no comenzó",
                    )

                    # Esperar a que FFmpeg genere el segundo WAV.
                    second_metadata = (
                        fragments_root
                        / str(session_id)
                        / "000001.json"
                    )

                    deadline = time.monotonic() + 12

                    while (
                        not second_metadata.exists()
                        and time.monotonic() < deadline
                    ):
                        time.sleep(0.05)

                    self.assertTrue(
                        second_metadata.exists(),
                        "FFmpeg no generó el segundo fragmento",
                    )

                    # El segundo fragmento apareció sin que el primer envío haya terminado.
                    self.assertFalse(
                        client.first_upload_finished.is_set(),
                        "El primer envío terminó antes de la comprobación",
                    )

                finally:
                    # Detener FFmpeg y liberar el backend para permitir el cierre controlado.
                    runner.stop()
                    client.release_first_upload.set()
                    thread.join(timeout=20)

                self.assertFalse(
                    thread.is_alive(),
                    "CaptureRunner no terminó",
                )

                self.assertEqual(errors, [])

                self.assertTrue(
                    client.first_upload_finished.is_set()
                )

                # Se enviaron al menos dos fragmentos.
                self.assertGreaterEqual(
                    len(client.uploaded_sequences),
                    2,
                )

                self.assertEqual(
                    client.uploaded_sequences[:2],
                    [0, 1],
                )

                # Todos los fragmentos publicados deben
                # estar confirmados al finalizar esta prueba.
                self.assertEqual(store.pending(), [])
                self.assertIsNone(runner.worker.failure)


if __name__ == "__main__":
    unittest.main()
