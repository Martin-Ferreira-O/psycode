
import json
import os
from pathlib import Path


class FragmentStoreError(Exception):
    """Error al gestionar el estado local de un fragmento."""


class FragmentStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _write_metadata(self, path: Path, metadata: dict):
        """Guardar cambios sin reemplazar un JSON con datos parciales."""
        temporary = path.with_name(path.name + ".part")

        with temporary.open("w", encoding="utf-8") as file:
            json.dump(metadata, file, indent=2)
            file.flush()
            os.fsync(file.fileno())

        os.replace(temporary, path)

    def _read_metadata(self, metadata_path: Path):
        try:
            with metadata_path.open("r", encoding="utf-8") as file:
                metadata = json.load(file)
        except (OSError, ValueError) as exc:
            raise FragmentStoreError(
                "No se pudo leer el manifiesto"
            ) from exc

        if not isinstance(metadata, dict):
            raise FragmentStoreError("Manifiesto inválido")

        return metadata

    def pending(self):
        """Recuperar fragmentos pendientes después de reiniciar."""
        fragments = []

        for metadata_path in self.root.glob("*/*.json"):
            metadata = self._read_metadata(metadata_path)

            if metadata.get("status", "pending") == "accepted":
                continue

            sequence = metadata.get("sequence")
            if type(sequence) is not int or sequence < 0:
                raise FragmentStoreError("Secuencia local inválida")

            filename = f"{sequence:06d}.wav"

            if metadata.get("filename") != filename:
                raise FragmentStoreError(
                    "Nombre de fragmento inconsistente"
                )

            audio_path = metadata_path.parent / filename

            if not audio_path.is_file():
                raise FragmentStoreError(
                    "Falta un WAV pendiente"
                )

            fragments.append({
                "metadata_path": metadata_path,
                "audio_path": audio_path,
                "metadata": metadata,
            })

        return sorted(
            fragments,
            key=lambda item: (
                str(item["metadata"].get("session_id", "")),
                item["metadata"]["sequence"],
            ),
        )

    def record_attempt(self, metadata_path: str | Path):
        """Registrar un nuevo intento de envío."""
        path = Path(metadata_path)
        metadata = self._read_metadata(path)

        if metadata.get("status") == "accepted":
            raise FragmentStoreError(
                "El fragmento ya fue aceptado"
            )

        metadata["status"] = "pending"
        metadata["attempts"] = metadata.get("attempts", 0) + 1

        self._write_metadata(path, metadata)
        return metadata

    def mark_accepted(
        self,
        metadata_path: str | Path,
        receipt: dict,
    ):
        """Guardar confirmación antes de eliminar el WAV."""
        path = Path(metadata_path)
        metadata = self._read_metadata(path)

        sequence = metadata["sequence"]
        audio_path = path.parent / f"{sequence:06d}.wav"

        if (
            receipt.get("estado") != "aceptado"
            or receipt.get("box") != metadata["box"]
            or receipt.get("session_id") != metadata["session_id"]
            or receipt.get("secuencia") != sequence
            or receipt.get("formato") != "wav"
            or receipt.get("checksum")
            != metadata["checksum_sha256"]
            or not audio_path.is_file()
            or receipt.get("size_bytes") != audio_path.stat().st_size
        ):
            raise FragmentStoreError(
                "La confirmación no coincide con el fragmento"
            )

        metadata["status"] = "accepted"
        metadata["receipt"] = receipt

        # Primero persistir la confirmación.
        self._write_metadata(path, metadata)

        # Solo después retirar el audio.
        audio_path.unlink()

        return metadata
