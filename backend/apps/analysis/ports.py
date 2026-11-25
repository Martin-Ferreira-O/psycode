from typing import Protocol
from .domain import Fragment, JevDecision, Transcription


class Transcriptor(Protocol):
    def transcribe(self, fragment: Fragment) -> Transcription: ...


class AnalizadorDeSenales(Protocol):
    def evaluate(self, current: dict, history: list[dict]) -> JevDecision: ...


class TechnicalAudit(Protocol):
    def failure(self, code: str, *, alerta_id=None, sesion_id=None, sequence=None) -> None: ...


class FragmentLedger(Protocol):
    def claim(self, fragment: Fragment) -> None: ...
