
import hashlib
import json
import tempfile
import unittest
import wave

from pathlib import Path

from .fragment_store import FragmentStore, FragmentStoreError


class FragmentStoreTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        self.root = Path(self.temp_dir.name) / "fragments"
        self.session_id = "11111111-1111-4111-8111-111111111111"
        self.session_folder = self.root / self.session_id
        self.session_folder.mkdir(parents=True)

        self.wav_path = self.session_folder / "000000.wav"
        self.metadata_path = self.session_folder / "000000.json"

        # Generar un WAV sintético sin datos clínicos.
        with wave.open(str(self.wav_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\x00\x00" * 16000)

        self.checksum = hashlib.sha256(
            self.wav_path.read_bytes()
        ).hexdigest()

        self.metadata = {
            "box": "box-5",
            "session_id": self.session_id,
            "sequence": 0,
            "filename": "000000.wav",
            "checksum_sha256": self.checksum,
            "captured_at": "2026-10-24T15:00:10Z",
            "duration_seconds": 1.0,
            "status": "pending",
            "attempts": 0,
        }

        self.metadata_path.write_text(
            json.dumps(self.metadata),
            encoding="utf-8",
        )

        self.store = FragmentStore(self.root)

    def crear_confirmacion(self):
        return {
            "job_id": "22222222-2222-4222-8222-222222222222",
            "session_id": self.session_id,
            "box": "box-5",
            "secuencia": 0,
            "formato": "wav",
            "checksum": self.checksum,
            "size_bytes": self.wav_path.stat().st_size,
            "estado": "aceptado",
        }

    def test_recuperar_pendientes_tras_reinicio(self):
        # Registrar un intento de envío.
        self.store.record_attempt(self.metadata_path)

        # Simular reinicio: crear otra instancia.
        recovered_store = FragmentStore(self.root)

        pendientes = recovered_store.pending()

        self.assertEqual(len(pendientes), 1)
        self.assertEqual(
            pendientes[0]["metadata"]["sequence"], 0
        )
        self.assertEqual(
            pendientes[0]["metadata"]["attempts"], 1
        )
        self.assertTrue(self.wav_path.exists())

    def test_eliminar_wav_despues_de_confirmacion(self):
        confirmacion = self.crear_confirmacion()

        self.store.mark_accepted(
            self.metadata_path,
            confirmacion,
        )

        # El WAV se elimina después de confirmar.
        self.assertFalse(self.wav_path.exists())

        # El manifiesto permanece como registro.
        self.assertTrue(self.metadata_path.exists())

        metadata = json.loads(
            self.metadata_path.read_text(encoding="utf-8")
        )

        self.assertEqual(metadata["status"], "accepted")
        self.assertEqual(
            metadata["receipt"]["job_id"],
            confirmacion["job_id"],
        )

        # Ya no aparece entre los pendientes.
        self.assertEqual(self.store.pending(), [])

    def test_no_eliminar_wav_con_confirmacion_invalida(self):
        confirmacion = self.crear_confirmacion()

        # Simular una confirmación de otro box.
        confirmacion["box"] = "box-3"

        with self.assertRaises(FragmentStoreError):
            self.store.mark_accepted(
                self.metadata_path,
                confirmacion,
            )

        # El archivo sigue disponible.
        self.assertTrue(self.wav_path.exists())
        self.assertEqual(len(self.store.pending()), 1)


if __name__ == "__main__":
    unittest.main()
