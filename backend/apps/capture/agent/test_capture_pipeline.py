
import json
import tempfile
import unittest

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

from .audio_chunker import save_fragment
from .backend_client import FragmentUploadError
from .fragment_store import FragmentStore
from .upload_queue import UploadQueue


class CapturePipelineTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        self.root = Path(self.temp_dir.name) / "fragments"
        self.session_id = UUID(
            "11111111-1111-4111-8111-111111111111"
        )
        self.folder = self.root / str(self.session_id)

        self.start_time = datetime(
            2026, 10, 24, 15, 0,
            tzinfo=timezone.utc,
        )

        audio = b"\x00\x00" * (16000 * 10)

        for sequence in range(2):
            save_fragment(
                folder=self.folder,
                box="box-5",
                session_id=self.session_id,
                sequence=sequence,
                audio=audio,
                captured_at=(
                    self.start_time
                    + timedelta(seconds=sequence * 9)
                ),
            )

        self.client = Mock()
        self.client.config.box_id = "box-5"

    def receipt(self, file_path, sequence, checksum):
        return {
            "job_id": f"job-{sequence}",
            "box": "box-5",
            "session_id": str(self.session_id),
            "secuencia": sequence,
            "formato": "wav",
            "checksum": checksum,
            "size_bytes": Path(file_path).stat().st_size,
            "estado": "aceptado",
        }

    def read_metadata(self, sequence):
        path = self.folder / f"{sequence:06d}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_recuperar_pipeline_tras_fallo(self):
        """Conserva pendientes y reanuda tras un reinicio."""

        enviados = []

        def primer_envio(
            file_path,
            session_id,
            sequence,
            captured_at,
            checksum,
        ):
            enviados.append((sequence, captured_at))

            if sequence == 1:
                raise FragmentUploadError(
                    "Fallo simulado del backend"
                )

            return self.receipt(
                file_path,
                sequence,
                checksum,
            )

        self.client.upload_fragment.side_effect = primer_envio

        store = FragmentStore(self.root)
        queue = UploadQueue(store, self.client)

        with self.assertRaises(FragmentUploadError):
            queue.process_pending()

        # Fragmento 0 aceptado: WAV eliminado.
        self.assertFalse(
            (self.folder / "000000.wav").exists()
        )
        self.assertEqual(
            self.read_metadata(0)["status"],
            "accepted",
        )

        # Fragmento 1 fallido: WAV conservado.
        self.assertTrue(
            (self.folder / "000001.wav").exists()
        )
        self.assertEqual(
            self.read_metadata(1)["status"],
            "pending",
        )

        # Simular reinicio del agente.
        recovered_store = FragmentStore(self.root)
        pending = recovered_store.pending()

        self.assertEqual(len(pending), 1)
        self.assertEqual(
            pending[0]["metadata"]["sequence"],
            1,
        )

        def segundo_envio(
            file_path,
            session_id,
            sequence,
            captured_at,
            checksum,
        ):
            enviados.append((sequence, captured_at))
            return self.receipt(
                file_path,
                sequence,
                checksum,
            )

        self.client.upload_fragment.side_effect = segundo_envio

        recovered_queue = UploadQueue(
            recovered_store,
            self.client,
        )

        uploaded = recovered_queue.process_pending()

        self.assertEqual(uploaded, 1)

        # Ambos fragmentos confirmados.
        self.assertEqual(recovered_store.pending(), [])

        for sequence in range(2):
            self.assertFalse(
                (self.folder / f"{sequence:06d}.wav").exists()
            )
            self.assertEqual(
                self.read_metadata(sequence)["status"],
                "accepted",
            )

        # Secuencia 0 enviada una vez;
        # secuencia 1 reintentada con timestamp idéntico.
        self.assertEqual(
            [sequence for sequence, _ in enviados],
            [0, 1, 1],
        )
        self.assertEqual(
            enviados[1][1],
            enviados[2][1],
        )


if __name__ == "__main__":
    unittest.main()
