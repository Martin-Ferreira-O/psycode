
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_PATH)


@dataclass(frozen=True)
class AgentConfig:
    box_id: str
    obs_host: str
    obs_port: int
    obs_password: str
    stream_url: str
    chunk_duration: int
    chunk_overlap: int

    # Configuración de SCRUM-73
    backend_url: str = ""
    agent_token: str = ""
    http_timeout: float = 15.0
    max_retries: int = 3
    retry_backoff: float = 2.0

    @classmethod
    def from_env(cls):
        box_id = os.getenv("BOX_ID", "").strip()

        valid_boxes = {f"box-{n}" for n in range(3, 8)}

        if box_id not in valid_boxes:
            raise ValueError(
                "BOX_ID debe estar entre box-3 y box-7"
            )

        password = os.getenv("OBSW_PASSWORD")

        if not password:
            raise ValueError(
                "OBSW_PASSWORD no está configurada"
            )

        duration = int(os.getenv("CHUNK_DURATION", "10"))
        overlap = int(os.getenv("CHUNK_OVERLAP", "1"))

        if duration <= 0:
            raise ValueError(
                "CHUNK_DURATION debe ser mayor que cero"
            )

        if not 0 <= overlap < duration:
            raise ValueError(
                "CHUNK_OVERLAP debe ser menor que la duración"
            )

        # Configuración HTTP
        backend_url = os.getenv(
            "PSYCODE_INTERNAL_BASE_URL", ""
        ).strip().rstrip("/")

        agent_token = os.getenv(
            "PSYCODE_AGENT_TOKEN", ""
        ).strip()

        http_timeout = float(
            os.getenv("HTTP_TIMEOUT", "15")
        )

        max_retries = int(
            os.getenv("MAX_RETRIES", "3")
        )

        retry_backoff = float(
            os.getenv("RETRY_BACKOFF", "2")
        )

        if http_timeout <= 0:
            raise ValueError(
                "HTTP_TIMEOUT debe ser mayor que cero"
            )

        if max_retries < 1:
            raise ValueError(
                "MAX_RETRIES debe ser al menos 1"
            )

        if retry_backoff < 0:
            raise ValueError(
                "RETRY_BACKOFF no puede ser negativo"
            )

        return cls(
            box_id=box_id,
            obs_host=os.getenv("OBSW_HOST", "127.0.0.1"),
            obs_port=int(os.getenv("OBSW_PORT", "4455")),
            obs_password=password,
            stream_url=os.getenv("STREAM_URL", ""),
            chunk_duration=duration,
            chunk_overlap=overlap,
            backend_url=backend_url,
            agent_token=agent_token,
            http_timeout=http_timeout,
            max_retries=max_retries,
            retry_backoff=retry_backoff,
        )
