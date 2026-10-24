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

        return cls(
            box_id=box_id,
            obs_host=os.getenv("OBSW_HOST", "127.0.0.1"),
            obs_port=int(os.getenv("OBSW_PORT", "4455")),
            obs_password=password,
            stream_url=os.getenv("STREAM_URL", ""),
            chunk_duration=duration,
            chunk_overlap=overlap,
        )