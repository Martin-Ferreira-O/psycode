"""Interfaces de consulta y escritura. Sin PyMongo ni tipos HTTP."""

from abc import ABC, abstractmethod

from .domain import Alerta, Evaluacion


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
