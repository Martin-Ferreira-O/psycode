
import threading
import unittest

from .upload_worker import UploadWorker


class FakeUploadQueue:
    """Simula una cola sin conexiones HTTP."""

    def __init__(self):
        self.calls = 0
        self.processed = threading.Event()

    def process_pending(self):
        self.calls += 1
        self.processed.set()

        # Simula un fragmento enviado.
        if self.calls == 1:
            return 1

        return 0


class UploadWorkerTests(unittest.TestCase):

    def test_worker_procesa_sin_bloquear(self):
        queue = FakeUploadQueue()

        worker = UploadWorker(
            queue=queue,
            interval_seconds=0.1,
        )

        worker.start()

        try:
            self.assertTrue(
                queue.processed.wait(timeout=3),
                "El worker no procesó la cola",
            )
        finally:
            stopped = worker.stop(timeout=3)

        self.assertTrue(stopped)
        self.assertEqual(worker.uploaded, 1)
        self.assertIsNone(worker.failure)
        self.assertGreaterEqual(queue.calls, 1)


    def test_finish_procesa_ultimo_pendiente(self):
        """El cierre realiza una última revisión de la cola."""

        class FakeQueue:
            def __init__(self):
                self.first_scan_done = threading.Event()
                self.has_pending = False
                self.uploaded = False
                self.calls = 0

            def process_pending(self):
                self.calls += 1

                if self.calls == 1:
                    self.first_scan_done.set()
                    return 0

                if self.has_pending:
                    self.has_pending = False
                    self.uploaded = True
                    return 1

                return 0

        queue = FakeQueue()

        worker = UploadWorker(
            queue=queue,
            interval_seconds=60,
        )

        worker.start()

        try:
            self.assertTrue(
                queue.first_scan_done.wait(timeout=3),
                "No se realizó la primera revisión",
            )

            # Simulamos que aparece un último WAV
            # después de la primera revisión.
            queue.has_pending = True

            # finish() debe despertar el worker
            # y procesarlo antes de terminar.
            finished = worker.finish(timeout=3)

            self.assertTrue(
                finished,
                "El worker no terminó",
            )

            self.assertTrue(queue.uploaded)
            self.assertEqual(worker.uploaded, 1)
            self.assertIsNone(worker.failure)

        finally:
            worker.stop(timeout=3)



if __name__ == "__main__":
    unittest.main()
