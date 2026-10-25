
import hashlib
import re
import time
from pathlib import Path
from uuid import UUID

import httpx

from .config import AgentConfig


class FragmentUploadError(Exception):
    """Error al enviar o confirmar un fragmento."""


class BackendClient:
    ENDPOINT = "/api/v1/internal/fragments"

    def __init__(self, config: AgentConfig):
        if not config.backend_url:
            raise ValueError("Backend no configurado")

        if not config.agent_token:
            raise ValueError("Token del agente no configurado")

        self.config = config
        self.url = config.backend_url.rstrip("/") + self.ENDPOINT

    def upload_fragment(
        self,
        file_path: str | Path,
        session_id: str,
        sequence: int,
        captured_at: str,
        checksum: str,
    ) -> dict:
        path = Path(file_path)

        if not path.is_file():
            raise FragmentUploadError("El fragmento no existe")

        size_bytes = path.stat().st_size

        if size_bytes == 0:
            raise FragmentUploadError("El fragmento está vacío")

        try:
            session_id = str(UUID(session_id))
        except (ValueError, AttributeError, TypeError) as exc:
            raise FragmentUploadError("session_id inválido") from exc

        if type(sequence) is not int or not 0 <= sequence <= 9223372036854775806:
            raise FragmentUploadError("Secuencia inválida")

        if not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise FragmentUploadError("Checksum inválido")

        if not captured_at:
            raise FragmentUploadError("captured_at es obligatorio")

        # Verificar los bytes antes de enviar.
        sha256 = hashlib.sha256()

        with path.open("rb") as audio:
            for block in iter(lambda: audio.read(1024 * 1024), b""):
                sha256.update(block)

        if sha256.hexdigest() != checksum:
            raise FragmentUploadError(
                "El checksum no corresponde al archivo"
            )

        headers = {
            "Authorization": f"Agent {self.config.agent_token}"
        }

        data = {
            "box": self.config.box_id,
            "session_id": session_id,
            "secuencia": str(sequence),
            "formato": "wav",
            "checksum": checksum,
            "captured_at": captured_at,
        }

        last_error = None

        for attempt in range(1, self.config.max_retries + 1):
            try:
                # Se abre nuevamente el MISMO WAV en cada intento.
                with path.open("rb") as audio:
                    response = httpx.post(
                        self.url,
                        headers=headers,
                        data=data,
                        files={
                            "archivo": (
                                path.name,
                                audio,
                                "audio/wav",
                            )
                        },
                        timeout=self.config.http_timeout,
                    )


                if response.status_code in (200, 201):
                    try:
                        payload = response.json()
                    except ValueError:
                        payload = None

                    receipt = (
                        payload.get("data")
                        if isinstance(payload, dict)
                        else None
                    )

                    if (
                        isinstance(receipt, dict)
                        and payload.get("success") is True
                        and receipt.get("estado") == "aceptado"
                        and receipt.get("box") == self.config.box_id
                        and receipt.get("session_id") == session_id
                        and receipt.get("secuencia") == sequence
                        and receipt.get("formato") == "wav"
                        and receipt.get("checksum") == checksum
                        and receipt.get("size_bytes") == size_bytes
                    ):
                        return receipt

                    last_error = "Confirmación inválida o incompleta"

                    if attempt < self.config.max_retries:
                        delay = self.config.retry_backoff * (
                            2 ** (attempt - 1)
                        )
                        time.sleep(delay)
                        continue

                    break


                if response.status_code < 500:
                    error_code = "UNKNOWN"

                    try:
                        error_code = response.json().get(
                            "error", {}
                        ).get("code", "UNKNOWN")
                    except (ValueError, AttributeError):
                        pass

                    raise FragmentUploadError(
                        f"Backend rechazó fragmento: "
                        f"HTTP {response.status_code}, {error_code}"
                    )

                last_error = f"HTTP {response.status_code}"

            except httpx.RequestError:
                last_error = "Error de conexión o timeout"

            if attempt < self.config.max_retries:
                delay = self.config.retry_backoff * (
                    2 ** (attempt - 1)
                )
                time.sleep(delay)

        raise FragmentUploadError(
            f"No se confirmó la recepción tras "
            f"{self.config.max_retries} intentos: {last_error}"
        )
