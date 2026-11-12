from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from backend.common.errors import ServiceError


class CaptureError(ServiceError):
    def __init__(self, code):
        super().__init__(code, "Operación de captura rechazada.", 409)


TECHNICAL_ERRORS = frozenset({
    "AGENT_START_FAILED", "AGENT_STOP_FAILED", "AGENT_INTERRUPTED",
    "AGENT_UNAVAILABLE", "SESSION_ABANDONED", "FINAL_SEQUENCE_TIMEOUT",
})


@dataclass(frozen=True)
class Command:
    command_id: UUID
    session_id: UUID
    box: str
    kind: str
    scheduled_start: datetime
    scheduled_end: datetime
    audio_chunk_duration: int | None = None


@dataclass(frozen=True)
class Session:
    session_id: UUID
    box: str
    state: str
    origin: str
    scheduled_start: datetime
    scheduled_end: datetime
    actual_start: datetime | None
    actual_end: datetime | None
    next_sequence: int
    final_sequence: int | None
    error_code: str
