"""Casos de uso de notifications; implementación pendiente de su tarea Jira."""
import logging
import os
from typing import Optional

from .clients import EmailClient, TeamsClient
from .domain import NotificationPayload, NotificationResult
from .ports import AlertNotifier, NotificationChannelClient

logger = logging.getLogger(__name__)


class NotificationService(AlertNotifier):
    def __init__(
        self,
        teams_client: Optional[NotificationChannelClient] = None,
        email_client: Optional[NotificationChannelClient] = None,
        enabled: Optional[bool] = None,
    ):
        self.teams_client = teams_client or TeamsClient()
        self.email_client = email_client or EmailClient()

        if enabled is not None:
            self.enabled = enabled
        else:
            self.enabled = os.getenv("NOTIFICATIONS_ENABLED", "false").lower() in ("true", "1", "yes")

    def notify_alert(self, alerta_id: str, payload: NotificationPayload) -> NotificationResult:
        if not alerta_id:
            logger.warning("Intento de notificación rechazado: alerta_id ausente")
            return NotificationResult(
                alerta_id="",
                enviado=False,
                motivo_omision="ALERTA_NO_ALMACENADA",
            )

        if not payload.debe_notificar():
            logger.info(
                f"[Audit] Notificación omitida para alerta={alerta_id} por nivel sin riesgo ({payload.nivel_riesgo})"
            )
            return NotificationResult(
                alerta_id=alerta_id,
                enviado=False,
                motivo_omision="NULO_O_SIN_RIESGO",
            )

        if not self.enabled:
            logger.info(f"[Audit] Notificaciones deshabilitadas localmente para alerta={alerta_id}")
            return NotificationResult(
                alerta_id=alerta_id,
                enviado=False,
                motivo_omision="NOTIFICATIONS_DISABLED",
            )

        intentos = []

        resultado_teams = self.teams_client.send(payload)
        intentos.append(resultado_teams)

        logger.info(
            f"[Audit] Intento Teams: alerta={alerta_id}, exito={resultado_teams.exitoso}, "
            f"duracion={resultado_teams.duracion_ms}ms, error={resultado_teams.error}"
        )

        if resultado_teams.exitoso:
            return NotificationResult(
                alerta_id=alerta_id,
                enviado=True,
                canal_exitoso="teams",
                intentos=intentos,
            )

        logger.warning(
            f"[Contingencia] Teams falló ({resultado_teams.error}). Activando fallback por correo para alerta={alerta_id}"
        )
        resultado_email = self.email_client.send(payload)
        intentos.append(resultado_email)

        logger.info(
            f"[Audit] Intento Correo: alerta={alerta_id}, exito={resultado_email.exitoso}, "
            f"duracion={resultado_email.duracion_ms}ms, error={resultado_email.error}"
        )

        if resultado_email.exitoso:
            return NotificationResult(
                alerta_id=alerta_id,
                enviado=True,
                canal_exitoso="email",
                intentos=intentos,
            )

        logger.error(
            f"[Fallo Doble] Fallaron Teams y Correo para alerta={alerta_id}. "
            "La alerta se mantiene almacenada y pendiente."
        )
        return NotificationResult(
            alerta_id=alerta_id,
            enviado=False,
            canal_exitoso=None,
            intentos=intentos,
            motivo_omision="FALLO_DOBLE_CANALES",
        )