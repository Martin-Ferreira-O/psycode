import threading
import unittest

from .upload_worker import UploadWorker


class ControlledQueue:
    def __init__(self):
        self.pending = [0]
        self.sent = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.lock = threading.Lock()
        self.calls = 0

    def process_pending(self):
        with self.lock:
            batch = list(self.pending)
            self.pending.clear()
            self.calls += 1
            first_call = self.calls == 1

        if first_call:
            self.started.set()
            if not self.release.wait(timeout=5):
                raise RuntimeError("Envio bloqueado")

        with self.lock:
            self.sent.extend(batch)

        return len(batch)


class StopDrainTests(unittest.TestCase):
    def test_envia_fragmento_pendiente_antes_de_terminar(self):
        queue = ControlledQueue()
        worker = UploadWorker(queue, interval_seconds=0.01)
        worker.start()

        self.assertTrue(queue.started.wait(timeout=2))

        with queue.lock:
            queue.pending.append(1)

        results = []

        finish_thread = threading.Thread(
            target=lambda: results.append(worker.finish(timeout=5))
        )
        finish_thread.start()

        self.assertTrue(
            worker._finish_requested.wait(timeout=2)
        )

        queue.release.set()
        finish_thread.join(timeout=6)

        self.assertFalse(finish_thread.is_alive())
        self.assertEqual(results, [True])
        self.assertEqual(queue.sent, [0, 1])
        self.assertEqual(queue.pending, [])
        self.assertEqual(worker.uploaded, 2)
        self.assertIsNone(worker.failure)


if __name__ == "__main__":
    unittest.main()
