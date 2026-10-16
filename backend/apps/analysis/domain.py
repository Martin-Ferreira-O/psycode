"""Contrato de salida Psycode 1.0; no depende de Django ni de proveedores."""
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
import math
from pathlib import Path
from uuid import UUID

CONTRACT_VERSION = "1.0"


class AnalysisState(StrEnum):
    SIGNAL = "senal"
    NO_SIGNAL = "sin_riesgo"
    INDETERMINATE = "indeterminado"


class FragmentRejected(ValueError):
    pass


@dataclass(frozen=True)
class Fragment:
    session_id: str
    sequence: int
    box: str
    captured_at: datetime
    path: Path = field(repr=False)
    start: int = 0
    end: int = 16000
    context_start: int = 0

    def __post_init__(self):
        if str(UUID(self.session_id)) != self.session_id:
            raise FragmentRejected("Sesión debe ser UUID canónico")
        if type(self.sequence) is not int or self.sequence < 0:
            raise FragmentRejected("Secuencia inválida")
        if (not all(type(v) is int for v in (self.context_start, self.start, self.end))
                or not 0 <= self.context_start <= self.start < self.end):
            raise FragmentRejected("Intervalo PCM inválido")
        if self.captured_at.tzinfo is None or not 1 <= len(self.box.strip()) <= 64:
            raise FragmentRejected("Fecha o box inválido")

    @property
    def id(self):
        return self.sequence


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float
    speaker: str | None

    def __post_init__(self):
        if not math.isfinite(self.start + self.end) or not 0 <= self.start <= self.end:
            raise ValueError("Tiempo de palabra inválido")


@dataclass(frozen=True)
class Transcription:
    text: str
    words: tuple[Word, ...]
    cleanup: str


@dataclass(frozen=True)
class Signal:
    category_id: str
    matrix_level: int
    severity: int
    excerpt: str
    start: float
    end: float
    speaker: str | None

    def __post_init__(self):
        if type(self.severity) is not int or self.severity not in (1, 2, 3):
            raise ValueError("Severidad debe estar entre 1 y 3")


@dataclass(frozen=True)
class JevDecision:
    model: str
    context: str
    values: tuple[float, ...]
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class AnalysisResult:
    session_id: str
    sequence: int
    state: AnalysisState
    transcription: Transcription | None = field(default=None, repr=False)
    signals: tuple[Signal, ...] = ()
    decisions: tuple[JevDecision, ...] = ()
    error_codes: tuple[str, ...] = ()
    contract_version: str = CONTRACT_VERSION
    questions_version: str = "habla-signals-1"

    def to_dict(self):
        return asdict(self)
