
import hashlib
import json
import tempfile
import unittest
import wave

from pathlib import Path
from unittest.mock import Mock

from .backend_client import FragmentUploadError
from .fragment_store import FragmentStore, FragmentStoreError
from .upload_queue import UploadQueue


class UploadQueueTests(unittest.TestCase):
    """Pruebas de integración local de la cola de envío."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        self.root = Path(self.temp_dir.name) / "fragments"
        self.session_id = "11111111-1111-4111-8111-111111111111"

        self.folder = self.root / self.session_id
        self.folder.mkdir(parents=True)

        self.wav_path = self.folder / "000000.wav"
        self.metadata_path = self.folder / "000000.json"

        # WAV sintético de 1 segundo, sin audio clínico.
        with wave.open(str(self.wav_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\x00\x00" * 16000)

        self.original_bytes = self.wav_path.read_bytes()
        self.checksum = hashlib.sha256(
            self.original_bytes
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

        # Simulación del backend: no realiza solicitudes HTTP.
        self.client = Mock()
        self.client.config.box_id = "box-5"

        self.receipt = {
            "job_id": "22222222-2222-4222-8222-222222222222",
            "session_id": self.session_id,
            "box": "box-5",
            "secuencia": 0,
            "formato": "wav",
            "checksum": self.checksum,
            "size_bytes": len(self.original_bytes),
            "estado": "aceptado",
        }

        self.queue = UploadQueue(self.store, self.client)

    def leer_metadata(self):
        return json.loads(
            self.metadata_path.read_text(encoding="utf-8")
        )

    def test_envio_exitoso_elimina_wav(self):
        """La confirmación válida permite eliminar el WAV."""
        self.client.upload_fragment.return_value = self.receipt

        uploaded = self.queue.process_pending()

        self.assertEqual(uploaded, 1)
        self.client.upload_fragment.assert_called_once_with(
            file_path=self.wav_path,
            session_id=self.session_id,
            sequence=0,
            captured_at="2026-10-24T15:00:10Z",
            checksum=self.checksum,
        )

        self.assertFalse(self.wav_path.exists())
        self.assertTrue(self.metadata_path.exists())

        metadata = self.leer_metadata()
        self.assertEqual(metadata["status"], "accepted")
        self.assertEqual(metadata["attempts"], 1)
        self.assertEqual(self.store.pending(), [])

    def test_error_backend_conserva_wav(self):
        """Un fallo de envío conserva el archivo pendiente."""
        self.client.upload_fragment.side_effect = (
            FragmentUploadError("Error HTTP simulado")
        )

        with self.assertRaises(FragmentUploadError):
            self.queue.process_pending()

        self.assertTrue(self.wav_path.exists())
        self.assertEqual(
            self.wav_path.read_bytes(),
            self.original_bytes,
        )

        metadata = self.leer_metadata()
        self.assertEqual(metadata["status"], "pending")
        self.assertEqual(metadata["attempts"], 1)

        # Simular un reinicio: crear un almacén nuevo.
        recovered_store = FragmentStore(self.root)

        pendientes = recovered_store.pending()
        self.assertEqual(len(pendientes), 1)
        self.assertEqual(
            pendientes[0]["metadata"]["sequence"],
            0,
        )

    def test_rechaza_fragmento_de_otro_box(self):
        """Un agente no debe enviar fragmentos de otro box."""
        self.metadata["box"] = "box-3"

        self.metadata_path.write_text(
            json.dumps(self.metadata),
            encoding="utf-8",
        )

        with self.assertRaises(FragmentStoreError):
            self.queue.process_pending()

        self.client.upload_fragment.assert_not_called()
        self.assertTrue(self.wav_path.exists())

        metadata = self.leer_metadata()
        self.assertEqual(metadata["attempts"], 0)


if __name__ == "__main__":
    unittest.main()
