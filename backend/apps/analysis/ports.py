"""Puertos consumidos por el trabajador interno de análisis."""
from typing import Protocol
from .domain import Fragment, JevDecision, Transcription


class Transcriptor(Protocol):
    def transcribe(self, fragment: Fragment) -> Transcription: ...


class AnalizadorDeSenales(Protocol):
    def evaluate(self, current: dict, history: list[dict]) -> JevDecision: ...


class TechnicalAudit(Protocol):
    def failure(self, code: str) -> None: ...


class FragmentLedger(Protocol):
    def claim(self, fragment: Fragment) -> None: ...
