"""Correo principal y contingencia; solo notificar alertas persistidas."""
from django.conf import settings

from backend.apps.alerts.audit import AlertAudit, ERROR_CODES
from backend.apps.alerts.domain import normalizar_uuid, DomainError
from backend.apps.alerts.exceptions import AlertNotFound
from backend.apps.alerts.repositories import AlertsRepository
from backend.common.errors import PersistenceUnavailable
from .clients import EmailClient
from .domain import AttemptResult, NotificationResult
from .ports import AlertNotifier


class NotificationService(AlertNotifier):
    def __init__(self, teams_client=None, email_client=None, enabled=None, *,
                 backup_email_client=None, store=None, audit=None):
        # Teams permanece fuera del flujo hasta que se decida su integración.
        self.email_client = email_client if email_client is not None else EmailClient()
        self.backup_email_client = (backup_email_client if backup_email_client is not None
                                    else EmailClient(backup=True))
        self.enabled = settings.NOTIFICATIONS_ENABLED if enabled is None else enabled
        self.store = store if store is not None else AlertsRepository()
        self.audit = audit if audit is not None else AlertAudit(self.store._events)

    def notify_alert(self, alerta_id, payload):
        if not payload.debe_notificar():
            return NotificationResult(alerta_id, False, motivo_omision='NULO_O_SIN_RIESGO')
        try:
            ident = normalizar_uuid(alerta_id, 'alerta_id')
            alert = self.store.get_alert(ident)
        except (DomainError, AlertNotFound, PersistenceUnavailable):
            return NotificationResult(alerta_id, False, motivo_omision='ALERTA_NO_ALMACENADA')
        if not self.enabled:
            return NotificationResult(ident, False, motivo_omision='NOTIFICATIONS_DISABLED')

        # Construir desde el registro confirmado; nunca enviar datos libres del llamador.
        from .domain import NotificationPayload
        payload = NotificationPayload(str(alert.semaforo), 'riesgo_suicida', alert.box,
                                      alert.fecha_hora.isoformat())
        attempts = []
        for backup, client in ((False, self.email_client), (True, self.backup_email_client)):
            try:
                result = client.send(payload)
            except TimeoutError:
                result = AttemptResult('email', False, 0, 'NOTIFICATION_TIMEOUT')
            except Exception:
                result = AttemptResult('email', False, 0, 'NOTIFICATION_INTERNAL_ERROR')
            # Ningún mensaje libre de un adaptador puede entrar a logs/bitácora.
            error = None if result.exitoso else (
                result.error if result.error in ERROR_CODES and result.error.startswith('NOTIFICATION_')
                else 'NOTIFICATION_INTERNAL_ERROR')
            result = AttemptResult('email', result.exitoso, result.duracion_ms, error)
            attempts.append(result)
            self.audit.record('notifications.send', 'success' if result.exitoso else 'failure',
                              alerta_id=ident, sesion_id=alert.sesion_id, channel='email',
                              backup=backup, duration_ms=result.duracion_ms, error_code=error)
            if result.exitoso:
                return NotificationResult(ident, True, canal_exitoso='email', intentos=attempts)
        return NotificationResult(ident, False, intentos=attempts, motivo_omision='FALLO_DOBLE_CANALES')
