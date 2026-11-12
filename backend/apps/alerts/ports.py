"""Interfaces de consulta y escritura. Sin PyMongo ni tipos HTTP."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .domain import Alerta, Evaluacion


@dataclass(frozen=True)
class AlertQueryFilters:
    q: Optional[str] = None
    fecha_desde_utc: Optional[datetime] = None
    fecha_hasta_utc: Optional[datetime] = None
    box: Optional[str] = None
    estado_evaluacion: Optional[str] = None
    revisadas: Optional[bool] = None
    limit: int = 50
    offset: int = 0
    registro_evaluaciones: bool = False


class AlertWritePort(ABC):
    @abstractmethod
    def insert_alert(self, alert: Alerta) -> Alerta:
        """Persiste una alerta pendiente. Duplicado → AlertAlreadyExists."""

    @abstractmethod
    def record_evaluation(self, alerta_id: str, evaluation: Evaluacion) -> Evaluacion:
        """Incrusta la evaluación atómicamente si sigue pendiente."""


class AlertQueryPort(ABC):
    @abstractmethod
    def get_alert(self, alerta_id: str) -> Alerta:
        """Detalle por UUID. Inexistente → AlertNotFound."""

    @abstractmethod
    def list_alerts(self, filters: AlertQueryFilters) -> tuple[list[Alerta], int]:
        """Consulta paginada y filtrada. Devuelve (items, total_count)."""
