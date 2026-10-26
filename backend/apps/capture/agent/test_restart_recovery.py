
import tempfile
import unittest

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from .audio_chunker import save_fragment
from .backend_client import FragmentUploadError
from .fragment_store import FragmentStore
from .upload_queue import UploadQueue


class FakeBackendClient:
    """Simula fallo o aceptación del backend."""

    def __init__(self, fail=False):
        self.config = SimpleNamespace(box_id="box-5")
        self.fail = fail
        self.received = []

    def upload_fragment(
        self,
        file_path,
        session_id,
        sequence,
        captured_at,
        checksum,
    ):
        self.received.append({
            "session_id": session_id,
            "sequence": sequence,
            "captured_at": captured_at,
            "checksum": checksum,
        })

        if self.fail:
            raise FragmentUploadError(
                "Conexión simulada interrumpida"
            )

        return {
            "estado": "aceptado",
            "box": self.config.box_id,
            "session_id": session_id,
            "secuencia": sequence,
            "formato": "wav",
            "checksum": checksum,
            "size_bytes": Path(file_path).stat().st_size,
        }


class RestartRecoveryTests(unittest.TestCase):

    def test_reenvio_tras_reinicio(self):
        """Recupera y envía el mismo WAV tras un fallo."""

        session_id = uuid4()
        captured_at = datetime.now(timezone.utc)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / str(session_id)

            # Generar un WAV sintético.
            metadata = save_fragment(
                folder=folder,
                box="box-5",
                session_id=session_id,
                sequence=0,
                audio=b"\x00\x00" * (16000 * 10),
                captured_at=captured_at,
            )

            wav_path = folder / "000000.wav"
            original_bytes = wav_path.read_bytes()

            # Primer intento: falla el backend.
            store = FragmentStore(root)
            failing_client = FakeBackendClient(fail=True)

            queue = UploadQueue(store, failing_client)

            with self.assertRaises(FragmentUploadError):
                queue.process_pending()

            self.assertTrue(wav_path.exists())
            self.assertEqual(
                wav_path.read_bytes(),
                original_bytes,
            )

            # Simular reinicio: crear nuevos objetos.
            recovered_store = FragmentStore(root)
            recovered_client = FakeBackendClient(
                fail=False
            )

            recovered_queue = UploadQueue(
                recovered_store,
                recovered_client,
            )

            # Recuperar el fragmento pendiente.
            pending = recovered_store.pending()

            self.assertEqual(len(pending), 1)

            recovered_metadata = pending[0]["metadata"]

            self.assertEqual(
                recovered_metadata["session_id"],
                metadata["session_id"],
            )
            self.assertEqual(
                recovered_metadata["sequence"],
                metadata["sequence"],
            )
            self.assertEqual(
                recovered_metadata["captured_at"],
                metadata["captured_at"],
            )
            self.assertEqual(
                recovered_metadata["checksum_sha256"],
                metadata["checksum_sha256"],
            )

            # Segundo intento: el backend acepta.
            uploaded = recovered_queue.process_pending()

            self.assertEqual(uploaded, 1)

            # Ambos intentos usaron la misma identidad.
            self.assertEqual(
                failing_client.received,
                recovered_client.received,
            )

            # La confirmación permite eliminar el WAV.
            self.assertFalse(wav_path.exists())
            self.assertEqual(
                recovered_store.pending(),
                [],
            )


if __name__ == "__main__":
    unittest.main()
