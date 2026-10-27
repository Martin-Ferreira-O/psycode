
import hashlib
import json
import subprocess
import tempfile
import threading
import unittest
import wave

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from . import audio_chunker


class FFmpegContinuoRealTests(unittest.TestCase):

    def test_captura_continua_y_detencion(self):
        """FFmpeg real captura hasta recibir stop_event."""

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            config = SimpleNamespace(
                box_id="box-5",
                stream_url="rtsp://127.0.0.1/test",
                chunk_duration=10,
                chunk_overlap=1,
            )

            session_id = uuid4()
            stop_event = threading.Event()
            notifications = []
            commands = []

            # Guardamos la función original antes del patch.
            real_popen = subprocess.Popen

            def use_realtime_audio(command, **kwargs):
                command = list(command)

                # Sustituir RTSP exclusivamente en esta prueba.
                index = command.index("-rtsp_transport")
                del command[index:index + 2]

                index = command.index("-i")
                command[index:index + 2] = [
                    "-re",
                    "-f", "lavfi",
                    "-i",
                    "sine=frequency=440:sample_rate=16000",
                ]

                commands.append(command)

                return real_popen(command, **kwargs)

            def on_fragment_saved(metadata):
                notifications.append(metadata)

                # Detener al guardar el primer fragmento.
                stop_event.set()

            # Protección por si FFmpeg no genera audio.
            watchdog = threading.Timer(
                30,
                stop_event.set,
            )

            watchdog.start()

            try:
                with (
                    patch.object(
                        audio_chunker,
                        "__file__",
                        str(root / "audio_chunker.py"),
                    ),
                    patch.object(
                        audio_chunker.subprocess,
                        "Popen",
                        side_effect=use_realtime_audio,
                    ),
                ):
                    output = audio_chunker.capture_audio(
                        config=config,
                        seconds=None,
                        session_id=session_id,
                        captured_at_start=datetime.now(
                            timezone.utc
                        ),
                        stop_event=stop_event,
                        on_fragment_saved=on_fragment_saved,
                    )
            finally:
                stop_event.set()
                watchdog.cancel()
                watchdog.join(timeout=1)

            # Se recibió al menos una notificación.
            self.assertGreaterEqual(len(notifications), 1)

            # El modo continuo no utiliza -t.
            self.assertEqual(len(commands), 1)
            self.assertNotIn("-t", commands[0])

            # Verificar que FFmpeg generó WAV reales.
            wav_files = sorted(output.glob("*.wav"))

            self.assertGreaterEqual(len(wav_files), 1)

            first_wav = wav_files[0]

            with wave.open(str(first_wav), "rb") as wav:
                self.assertEqual(wav.getnchannels(), 1)
                self.assertEqual(wav.getframerate(), 16000)
                self.assertEqual(wav.getsampwidth(), 2)

                duration = (
                    wav.getnframes() / wav.getframerate()
                )

            self.assertAlmostEqual(
                duration,
                10.0,
                places=2,
            )

            # Comprobar el manifiesto del primer WAV.
            metadata_path = output / "000000.json"

            metadata = json.loads(
                metadata_path.read_text(encoding="utf-8")
            )

            self.assertEqual(metadata["sequence"], 0)
            self.assertEqual(metadata["status"], "pending")

            self.assertEqual(
                metadata["session_id"],
                str(session_id),
            )

            checksum = hashlib.sha256(
                first_wav.read_bytes()
            ).hexdigest()

            self.assertEqual(
                metadata["checksum_sha256"],
                checksum,
            )


if __name__ == "__main__":
    unittest.main()
