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
        pass

    @abstractmethod
    def record_evaluation(self, alerta_id: str, evaluation: Evaluacion) -> Evaluacion:
        pass


class AlertQueryPort(ABC):
    @abstractmethod
    def get_alert(self, alerta_id: str) -> Alerta:
        pass

    @abstractmethod
    def list_alerts(self, filters: AlertQueryFilters) -> tuple[list[Alerta], int]:
        pass
