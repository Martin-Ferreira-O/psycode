from abc import ABC, abstractmethod
from .domain import AttemptResult, NotificationPayload, NotificationResult


class NotificationChannelClient(ABC):
    @property
    @abstractmethod
    def nombre_canal(self) -> str:
        pass

    @abstractmethod
    def send(self, payload: NotificationPayload) -> AttemptResult:
        pass


class AlertNotifier(ABC):
    @abstractmethod
    def notify_alert(self, alerta_id: str, payload: NotificationPayload) -> NotificationResult:
        pass