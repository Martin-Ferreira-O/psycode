
import hashlib
import json
import subprocess
import tempfile
import unittest
import wave

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from . import audio_chunker


class FFmpegRealTests(unittest.TestCase):

    def test_fragmentacion_con_ffmpeg_real(self):
        """Procesa audio sintético con FFmpeg real."""

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "audio_sintetico.wav"

            # Generar 25 segundos de audio.
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel", "error",
                    "-y",
                    "-f", "lavfi",
                    "-i",
                    "sine=frequency=440:sample_rate=16000:duration=25",
                    "-ac", "1",
                    "-ar", "16000",
                    "-c:a", "pcm_s16le",
                    str(source),
                ],
                check=True,
            )

            config = SimpleNamespace(
                box_id="box-5",
                stream_url="rtsp://127.0.0.1/test",
                chunk_duration=10,
                chunk_overlap=1,
            )

            session_id = uuid4()

            real_popen = subprocess.Popen

            def use_local_audio(command, **kwargs):
                # Solo en esta prueba sustituimos RTSP
                # por el archivo WAV sintético.
                command = list(command)

                index = command.index("-rtsp_transport")
                del command[index:index + 2]

                input_index = command.index("-i")
                command[input_index + 1] = str(source)

                return real_popen(command, **kwargs)

            # Evitar guardar fragmentos dentro del repositorio.
            temporary_module_path = root / "audio_chunker.py"

            with (
                patch.object(
                    audio_chunker,
                    "__file__",
                    str(temporary_module_path),
                ),
                patch.object(
                    audio_chunker.subprocess,
                    "Popen",
                    side_effect=use_local_audio,
                ),
            ):
                output = audio_chunker.capture_audio(
                    config=config,
                    seconds=25,
                    session_id=session_id,
                    captured_at_start=datetime.now(
                        timezone.utc
                    ),
                )

            wav_files = sorted(output.glob("*.wav"))
            json_files = sorted(output.glob("*.json"))

            self.assertEqual(len(wav_files), 3)
            self.assertEqual(len(json_files), 3)

            durations = []
            samples = []

            for sequence, path in enumerate(wav_files):
                with wave.open(str(path), "rb") as wav:
                    self.assertEqual(wav.getnchannels(), 1)
                    self.assertEqual(wav.getframerate(), 16000)
                    self.assertEqual(wav.getsampwidth(), 2)

                    durations.append(
                        wav.getnframes() / wav.getframerate()
                    )
                    samples.append(wav.readframes(wav.getnframes()))

                metadata_path = output / f"{sequence:06d}.json"

                metadata = json.loads(
                    metadata_path.read_text(encoding="utf-8")
                )

                self.assertEqual(metadata["sequence"], sequence)
                self.assertEqual(metadata["status"], "pending")
                self.assertEqual(metadata["box"], "box-5")
                self.assertEqual(
                    metadata["session_id"],
                    str(session_id),
                )

                checksum = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()

                self.assertEqual(
                    metadata["checksum_sha256"],
                    checksum,
                )

            # Duraciones esperadas: 10, 10 y 7 segundos.
            for actual, expected in zip(
                durations,
                [10.0, 10.0, 7.0],
            ):
                self.assertAlmostEqual(
                    actual,
                    expected,
                    places=2,
                )

            # Comprobar un segundo de solapamiento.
            overlap_bytes = 16000 * 2

            self.assertEqual(
                samples[0][-overlap_bytes:],
                samples[1][:overlap_bytes],
            )

            self.assertEqual(
                samples[1][-overlap_bytes:],
                samples[2][:overlap_bytes],
            )


if __name__ == "__main__":
    unittest.main()
