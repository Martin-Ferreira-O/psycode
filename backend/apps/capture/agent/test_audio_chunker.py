
import hashlib
import json
import tempfile
import unittest
import wave

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from .audio_chunker import save_fragment
from .fragment_store import FragmentStore


class AudioChunkerTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        self.root = Path(self.temp_dir.name) / "fragments"

        self.session_id = UUID(
            "11111111-1111-4111-8111-111111111111"
        )

        self.folder = self.root / str(self.session_id)

        self.start_time = datetime(
            2026, 10, 24, 15, 0, 0,
            tzinfo=timezone.utc,
        )

        # Audio sintético: 10 segundos de silencio PCM.
        self.audio = b"\x00\x00" * (16000 * 10)

    def guardar(self, sequence, captured_at):
        return save_fragment(
            folder=self.folder,
            box="box-5",
            session_id=self.session_id,
            sequence=sequence,
            audio=self.audio,
            captured_at=captured_at,
        )

    def test_generar_wav_y_metadata(self):
        """Genera WAV válido y manifiesto completo."""

        metadata = self.guardar(0, self.start_time)

        wav_path = self.folder / "000000.wav"
        json_path = self.folder / "000000.json"

        self.assertTrue(wav_path.exists())
        self.assertTrue(json_path.exists())

        with wave.open(str(wav_path), "rb") as wav:
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getsampwidth(), 2)
            self.assertEqual(wav.getframerate(), 16000)
            self.assertEqual(wav.getnframes(), 160000)

        checksum = hashlib.sha256(
            wav_path.read_bytes()
        ).hexdigest()

        self.assertEqual(
            metadata["checksum_sha256"],
            checksum,
        )

        self.assertEqual(metadata["box"], "box-5")
        self.assertEqual(metadata["sequence"], 0)
        self.assertEqual(metadata["status"], "pending")
        self.assertEqual(metadata["attempts"], 0)
        self.assertEqual(metadata["duration_seconds"], 10.0)

        self.assertEqual(
            metadata["captured_at"],
            "2026-10-24T15:00:00.000Z",
        )

        saved_metadata = json.loads(
            json_path.read_text(encoding="utf-8")
        )

        self.assertEqual(saved_metadata, metadata)

    def test_fragmentos_compatibles_con_store(self):
        """FragmentStore reconoce los WAV generados."""

        self.guardar(0, self.start_time)

        # Referencia temporal de laboratorio:
        # fragmentos de 10 s con 1 s de solapamiento.
        self.guardar(
            1,
            self.start_time + timedelta(seconds=9),
        )

        store = FragmentStore(self.root)
        pending = store.pending()

        self.assertEqual(len(pending), 2)

        self.assertEqual(
            [item["metadata"]["sequence"] for item in pending],
            [0, 1],
        )

        self.assertEqual(
            pending[1]["metadata"]["captured_at"],
            "2026-10-24T15:00:09.000Z",
        )

    def test_rechazar_timestamp_sin_zona_horaria(self):
        """No permite timestamps sin zona horaria."""

        naive_time = datetime(2026, 10, 24, 15, 0, 0)

        with self.assertRaises(ValueError):
            self.guardar(0, naive_time)

        self.assertFalse(
            (self.folder / "000000.wav").exists()
        )


if __name__ == "__main__":
    unittest.main()
