
import threading
from pathlib import Path
from uuid import UUID

from datetime import datetime

from .audio_chunker import capture_audio
from .backend_client import BackendClient
from .config import AgentConfig
from .fragment_store import FragmentStore
from .upload_queue import UploadQueue
from .upload_worker import UploadWorker


class CaptureRunner:
    """Coordina captura continua y envío HTTP."""

    def __init__(self, config: AgentConfig):
        self.config = config

        # Debe coincidir con la ruta de audio_chunker.py.
        self.fragments_root = (
            Path(__file__).resolve().parent / "fragments"
        )

        self.store = FragmentStore(self.fragments_root)
        self.client = BackendClient(config)
        self.queue = UploadQueue(self.store, self.client)
        self.stop_event = threading.Event()
        self.worker = UploadWorker(self.queue, on_failure=self.stop)

    def run(
        self,
        session_id: UUID,
        captured_at_start: datetime,
        seconds: int | None = None,
    ) -> Path:
        """Captura audio y envía fragmentos en paralelo."""

        self.worker.start()

        try:
            output = capture_audio(
                config=self.config,
                seconds=seconds,
                session_id=session_id,
                captured_at_start=captured_at_start,
                stop_event=self.stop_event,
                on_fragment_saved=lambda metadata: (
                    self.worker.notify_new_fragment()
                ),
            )
        finally:
            worker_stopped = self.worker.finish(timeout=20)

        if not worker_stopped:
            raise RuntimeError(
                "El worker de envío no terminó"
            )

        if self.worker.failure is not None:
            raise RuntimeError(
                f"Fallo técnico del worker: "
                f"{self.worker.failure}"
            )

        return output

    def stop(self):
        """Solicita detener la captura."""

        self.stop_event.set()
