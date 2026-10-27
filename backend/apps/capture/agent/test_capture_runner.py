
import threading
import unittest
import tempfile

from .audio_chunker import save_fragment
from .backend_client import FragmentUploadError
from .fragment_store import FragmentStore

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from .capture_runner import CaptureRunner


class SlowUploadQueue:
    """Simula un envío HTTP que tarda en finalizar."""

    def __init__(self):
        self.pending = threading.Event()
        self.upload_started = threading.Event()
        self.release_upload = threading.Event()
        self.upload_finished = threading.Event()

    def process_pending(self):
        if not self.pending.is_set():
            return 0

        self.pending.clear()
        self.upload_started.set()

        if not self.release_upload.wait(timeout=5):
            raise RuntimeError("El envío quedó bloqueado")

        self.upload_finished.set()
        return 1


class CaptureRunnerTests(unittest.TestCase):

    def test_captura_continua_mientras_envia(self):
        """La captura puede avanzar durante un envío pendiente."""

        queue = SlowUploadQueue()

        capture_advanced = threading.Event()
        finish_capture = threading.Event()

        errors = []
        results = []

        config = SimpleNamespace(
            box_id="box-5",
        )

        session_id = uuid4()

        def fake_capture_audio(
            config,
            seconds,
            session_id,
            captured_at_start,
            stop_event,
            on_fragment_saved,
        ):
            # Simula la generación del primer fragmento.
            queue.pending.set()
            on_fragment_saved({"sequence": 0})

            if not queue.upload_started.wait(timeout=5):
                raise RuntimeError("El envío no comenzó")

            # La captura sigue avanzando aunque el
            # envío HTTP todavía no termina.
            capture_advanced.set()

            if not finish_capture.wait(timeout=5):
                raise RuntimeError("La captura no finalizó")

            return Path("test/session")

        def run_agent(runner):
            try:
                result = runner.run(
                    session_id=session_id,
                    captured_at_start=datetime.now(timezone.utc),
                    seconds=None,
                )
                results.append(result)
            except Exception as exc:
                errors.append(exc)

        with (
            patch(
                "backend.apps.capture.agent.capture_runner.FragmentStore"
            ),
            patch(
                "backend.apps.capture.agent.capture_runner.BackendClient"
            ),
            patch(
                "backend.apps.capture.agent.capture_runner.UploadQueue",
                return_value=queue,
            ),
            patch(
                "backend.apps.capture.agent.capture_runner.capture_audio",
                side_effect=fake_capture_audio,
            ),
        ):
            runner = CaptureRunner(config)

            agent_thread = threading.Thread(
                target=run_agent,
                args=(runner,),
                daemon=True,
            )

            agent_thread.start()

            try:
                self.assertTrue(
                    queue.upload_started.wait(timeout=5),
                    "El worker no inició el envío",
                )

                self.assertTrue(
                    capture_advanced.wait(timeout=5),
                    "La captura no avanzó",
                )

                # La captura avanzó mientras el
                # envío todavía estaba pendiente.
                self.assertFalse(
                    queue.upload_finished.is_set()
                )

            finally:
                # Permitir finalizar ambos componentes.
                queue.release_upload.set()
                finish_capture.set()
                agent_thread.join(timeout=5)

        self.assertFalse(agent_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results, [Path("test/session")])

        self.assertTrue(queue.upload_finished.is_set())
        self.assertEqual(runner.worker.uploaded, 1)
        self.assertIsNone(runner.worker.failure)


    def test_cierre_envia_ultimo_fragmento(self):
        """El runner procesa el último pendiente antes de terminar."""

        class FakeQueue:
            def __init__(self):
                self.first_scan_done = threading.Event()
                self.pending_fragment = False
                self.uploaded = False
                self.calls = 0

            def process_pending(self):
                self.calls += 1

                # Primera revisión: todavía no hay WAV.
                if self.calls == 1:
                    self.first_scan_done.set()
                    return 0

                # Segunda revisión: aparece el último WAV.
                if self.pending_fragment:
                    self.pending_fragment = False
                    self.uploaded = True
                    return 1

                return 0

        queue = FakeQueue()

        config = SimpleNamespace(box_id="box-5")

        def fake_capture_audio(
            config,
            seconds,
            session_id,
            captured_at_start,
            stop_event,
            on_fragment_saved,
        ):
            # Esperar la primera revisión del worker.
            if not queue.first_scan_done.wait(timeout=3):
                raise RuntimeError(
                    "El worker no realizó su primera revisión"
                )

            # Simular que FFmpeg guarda el último WAV.
            queue.pending_fragment = True
            on_fragment_saved({"sequence": 0})

            # La captura termina inmediatamente después.
            return Path("test/closing-session")

        with (
            patch(
                "backend.apps.capture.agent.capture_runner.FragmentStore"
            ),
            patch(
                "backend.apps.capture.agent.capture_runner.BackendClient"
            ),
            patch(
                "backend.apps.capture.agent.capture_runner.UploadQueue",
                return_value=queue,
            ),
            patch(
                "backend.apps.capture.agent.capture_runner.capture_audio",
                side_effect=fake_capture_audio,
            ),
        ):
            runner = CaptureRunner(config)

            result = runner.run(
                session_id=uuid4(),
                captured_at_start=datetime.now(timezone.utc),
                seconds=None,
            )

        self.assertEqual(
            result,
            Path("test/closing-session"),
        )

        # El último fragmento fue procesado.
        self.assertTrue(queue.uploaded)
        self.assertFalse(queue.pending_fragment)

        # Hubo al menos una revisión adicional.
        self.assertGreaterEqual(queue.calls, 2)

        # El worker terminó sin errores.
        self.assertEqual(runner.worker.uploaded, 1)
        self.assertIsNone(runner.worker.failure)


    def test_conserva_ultimo_wav_si_falla_backend(self):
        """Un fallo HTTP no debe eliminar un WAV pendiente."""

        class FakeBackendClient:
            def __init__(self):
                self.config = SimpleNamespace(box_id="box-5")
                self.calls = 0

            def upload_fragment(self, **kwargs):
                self.calls += 1
                raise FragmentUploadError(
                    "Fallo de conexión simulado"
                )

        client = FakeBackendClient()
        session_id = uuid4()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = FragmentStore(root)

            def fake_capture_audio(
                config,
                seconds,
                session_id,
                captured_at_start,
                stop_event,
                on_fragment_saved,
            ):
                folder = root / str(session_id)

                # Audio sintético: 10 segundos,
                # PCM mono de 16 kHz y 16 bits.
                audio = b"\x00\x00" * (16000 * 10)

                metadata = save_fragment(
                    folder=folder,
                    box="box-5",
                    session_id=session_id,
                    sequence=0,
                    audio=audio,
                    captured_at=captured_at_start,
                )

                # Notificar al worker.
                on_fragment_saved(metadata)

                return folder

            with (
                patch(
                    "backend.apps.capture.agent.capture_runner.FragmentStore",
                    return_value=store,
                ),
                patch(
                    "backend.apps.capture.agent.capture_runner.BackendClient",
                    return_value=client,
                ),
                patch(
                    "backend.apps.capture.agent.capture_runner.capture_audio",
                    side_effect=fake_capture_audio,
                ),
            ):
                runner = CaptureRunner(
                    SimpleNamespace(box_id="box-5")
                )

                # El error debe llegar al coordinador.
                with self.assertRaisesRegex(
                    RuntimeError,
                    "Fallo técnico del worker",
                ):
                    runner.run(
                        session_id=session_id,
                        captured_at_start=datetime.now(timezone.utc),
                        seconds=None,
                    )

            # El cliente intentó enviar el WAV.
            self.assertEqual(client.calls, 1)

            # El WAV debe seguir pendiente en disco.
            pending = store.pending()

            self.assertEqual(len(pending), 1)

            fragment = pending[0]

            self.assertTrue(
                fragment["audio_path"].is_file()
            )

            self.assertEqual(
                fragment["metadata"]["status"],
                "pending",
            )

            self.assertGreaterEqual(
                fragment["metadata"]["attempts"],
                1,
            )

            self.assertEqual(
                runner.worker.failure,
                "FragmentUploadError: Fallo de conexión simulado",
            )



if __name__ == "__main__":
    unittest.main()
