"""Interfaz interna: el adaptador de transporte debe autenticar el box."""
from datetime import datetime
from typing import Protocol
from uuid import UUID

from .domain import Command, Session


class BoxAgentControl(Protocol):
    def commands(self, box: str, *, now: datetime | None = None) -> tuple[Command, ...]: ...

    def acknowledge(self, box: str, command_id: UUID, *, success: bool = True,
                    last_sequence: int | None = None, error_code: str = "",
                    occurred_at: datetime | None = None, now: datetime | None = None) -> Session: ...

    def accept_sequence(self, box: str, session_id: UUID, number: int,
                        captured_at: datetime, *, now: datetime | None = None) -> bool: ...

    def heartbeat(self, box: str, session_id: UUID, *, now: datetime | None = None) -> Session: ...

    def interrupted(self, box: str, session_id: UUID, *, error_code: str = "AGENT_INTERRUPTED",
                    now: datetime | None = None) -> Session: ...
