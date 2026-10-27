import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from .fragment_store import FragmentStore, FragmentStoreError


class LastSequenceTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.store = FragmentStore(self.temp.name)
        self.session_id = uuid4()
        self.folder = Path(self.temp.name) / str(self.session_id)
        self.folder.mkdir()

    def save_metadata(self, sequence, status):
        metadata = {
            "session_id": str(self.session_id),
            "sequence": sequence,
            "filename": f"{sequence:06d}.wav",
            "status": status,
        }

        path = self.folder / f"{sequence:06d}.json"
        self.store._write_metadata(path, metadata)

    def test_sesion_sin_fragmentos(self):
        self.assertEqual(
            self.store.last_sequence(self.session_id),
            -1,
        )

    def test_incluye_fragmentos_aceptados(self):
        self.save_metadata(0, "accepted")
        self.save_metadata(1, "accepted")
        self.save_metadata(2, "pending")

        # Los fragmentos aceptados ya no tienen WAV.
        self.assertEqual(
            self.store.last_sequence(self.session_id),
            2,
        )

    def test_recuperacion_despues_de_reiniciar(self):
        self.save_metadata(0, "accepted")
        self.save_metadata(1, "accepted")

        # Simulamos otra instancia del agente.
        recovered_store = FragmentStore(self.temp.name)

        self.assertEqual(
            recovered_store.last_sequence(self.session_id),
            1,
        )

    def test_sesion_independiente(self):
        self.save_metadata(0, "accepted")

        another_session = uuid4()

        self.assertEqual(
            self.store.last_sequence(another_session),
            -1,
        )

    def test_manifiesto_invalido(self):
        self.save_metadata(0, "accepted")

        path = self.folder / "000000.json"
        path.write_text('{"sequence": "incorrecta"}', encoding="utf-8")

        with self.assertRaises(FragmentStoreError):
            self.store.last_sequence(self.session_id)