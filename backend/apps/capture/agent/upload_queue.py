
from pathlib import Path

from .backend_client import BackendClient, FragmentUploadError
from .fragment_store import FragmentStore, FragmentStoreError


class UploadQueue:
    """Coordina el envío de fragmentos pendientes a SCRUM-73."""

    def __init__(
        self,
        store: FragmentStore,
        client: BackendClient,
    ):
        self.store = store
        self.client = client

    def process_pending(self) -> int:
        """Procesa los fragmentos pendientes en orden."""

        uploaded = 0

        for fragment in self.store.pending():
            metadata_path = Path(fragment["metadata_path"])
            audio_path = Path(fragment["audio_path"])
            metadata = fragment["metadata"]

            required_fields = (
                "box",
                "session_id",
                "sequence",
                "checksum_sha256",
                "captured_at",
            )

            if any(
                field not in metadata
                for field in required_fields
            ):
                raise FragmentStoreError(
                    "Fragmento con metadatos incompletos"
                )

            if metadata["box"] != self.client.config.box_id:
                raise FragmentStoreError(
                    "El fragmento pertenece a otro box"
                )

            self.store.record_attempt(metadata_path)

            try:
                receipt = self.client.upload_fragment(
                    file_path=audio_path,
                    session_id=metadata["session_id"],
                    sequence=metadata["sequence"],
                    captured_at=metadata["captured_at"],
                    checksum=metadata["checksum_sha256"],
                )
            except FragmentUploadError:
                raise


            self.store.mark_accepted(
                metadata_path,
                receipt,
            )

            uploaded += 1

        return uploaded
