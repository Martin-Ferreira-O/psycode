
import threading

from .backend_client import FragmentUploadError
from .fragment_store import FragmentStoreError
from .upload_queue import UploadQueue


class UploadWorker:
    """Envía fragmentos pendientes sin bloquear la captura."""

    def __init__(
        self,
        queue: UploadQueue,
        interval_seconds: float = 1.0,
    ):
        if interval_seconds <= 0:
            raise ValueError(
                "El intervalo debe ser positivo"
            )

        self.queue = queue
        self.interval_seconds = interval_seconds

        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._finish_requested = threading.Event()

        self._thread = None

        self.uploaded = 0
        self.failure = None

    def start(self):
        """Inicia el hilo de envío."""

        if self._thread is not None:
            raise RuntimeError(
                "El worker ya fue iniciado"
            )

        self._thread = threading.Thread(
            target=self._run,
            name="capture-upload-worker",
            daemon=True,
        )

        self._thread.start()

    def notify_new_fragment(self):
        """Solicita revisar los fragmentos pendientes."""

        self._wake_event.set()

    def _run(self):
        """Procesa pendientes y admite un cierre controlado."""

        while not self._stop_event.is_set():

            # Si se solicitó finalizar antes de esta iteración, esta será la última revisión.
            finishing_this_pass = (
                self._finish_requested.is_set()
            )

            try:
                count = self.queue.process_pending()
                self.uploaded += count

            except (FragmentUploadError, FragmentStoreError) as exc:
                self.failure = f"{type(exc).__name__}: {exc}"
                return

            except Exception as exc:
                self.failure = type(exc).__name__
                return

            if finishing_this_pass:
                return

            self._wake_event.wait(
                self.interval_seconds
            )

            self._wake_event.clear()

    def finish(self, timeout: float = 20.0) -> bool:
        """
        Solicita una última revisión de pendientes.

        Debe llamarse después de finalizar la captura,
        cuando ya no se generarán nuevos fragmentos.

        Devuelve True si el hilo terminó.
        No elimina WAV pendientes sin confirmación.
        """

        self._finish_requested.set()
        self._wake_event.set()

        if self._thread is None:
            return True

        self._thread.join(timeout=timeout)

        return not self._thread.is_alive()

    def stop(self, timeout: float = 10.0) -> bool:
        """
        Detiene el worker sin exigir una última revisión.

        Los fragmentos pendientes permanecen en disco.
        """

        self._stop_event.set()
        self._wake_event.set()

        if self._thread is None:
            return True

        self._thread.join(timeout=timeout)

        return not self._thread.is_alive()
