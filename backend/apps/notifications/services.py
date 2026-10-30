from django.conf import settings

from backend.apps.alerts.audit import AlertAudit, ERROR_CODES
from backend.apps.alerts.domain import DomainError, normalizar_uuid
from backend.apps.alerts.exceptions import AlertNotFound
from backend.apps.alerts.repositories import AlertsRepository
from backend.apps.operational.models import NotificationMode
from backend.common.errors import PersistenceUnavailable
from .clients import EmailClient
from .domain import AttemptResult, NotificationPayload, NotificationResult
from .ports import AlertNotifier
from .recipients import RecipientResolver


class NotificationService(AlertNotifier):
    def __init__(self, teams_client=None, email_client=None, enabled=None, *,
                 backup_email_client=None, store=None, audit=None, recipient_resolver=None):
        self.recipient_resolver = recipient_resolver if recipient_resolver is not None else RecipientResolver()
        self.email_client = email_client if email_client is not None else EmailClient()
        self.backup_email_client = (
            backup_email_client if backup_email_client is not None else EmailClient(destinatarios=[])
        )
        self.enabled = settings.NOTIFICATIONS_ENABLED if enabled is None else enabled
        self.store = store if store is not None else AlertsRepository()
        self.audit = audit if audit is not None else AlertAudit(self.store._events)

    def _deliver(self, client, payload, email, ident, sesion_id, *, backup: bool) -> AttemptResult:
        recipients = [email] if email else []
        try:
            if not recipients:
                result = AttemptResult('email', False, 0, 'NOTIFICATION_NOT_CONFIGURED')
            else:
                result = client.send(payload, destinatarios=recipients)
        except TimeoutError:
            result = AttemptResult('email', False, 0, 'NOTIFICATION_TIMEOUT')
        except Exception:
            result = AttemptResult('email', False, 0, 'NOTIFICATION_INTERNAL_ERROR')

        error = None if result.exitoso else (
            result.error if result.error in ERROR_CODES and result.error.startswith('NOTIFICATION_')
            else 'NOTIFICATION_INTERNAL_ERROR'
        )
        sanitized = AttemptResult('email', result.exitoso, result.duracion_ms, error)
        self.audit.record(
            'notifications.send',
            'success' if sanitized.exitoso else 'failure',
            alerta_id=ident,
            sesion_id=sesion_id,
            channel='email',
            backup=backup,
            duration_ms=sanitized.duracion_ms,
            error_code=error,
        )
        return sanitized

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

        confirmed_payload = NotificationPayload(
            str(alert.semaforo), 'riesgo_suicida', alert.box, alert.fecha_hora.isoformat()
        )
        recipients = self.recipient_resolver.resolve()
        backup_enabled = bool(getattr(recipients, 'backup_enabled', False))
        backup_email = getattr(recipients, 'backup_email', None)

        if recipients.reason:
            if recipients.mode == NotificationMode.ACTIVE_SUPERVISORS and backup_enabled:
                backup_attempt = self._deliver(
                    self.backup_email_client,
                    confirmed_payload,
                    backup_email,
                    ident,
                    alert.sesion_id,
                    backup=True,
                )
                status = 'FALLO_PARCIAL' if backup_attempt.exitoso else 'FALLO_TOTAL'
                return NotificationResult(
                    ident,
                    backup_attempt.exitoso,
                    canal_exitoso='email' if backup_attempt.exitoso else None,
                    intentos=[backup_attempt],
                    estado=status,
                )
            return NotificationResult(
                ident,
                False,
                motivo_omision=recipients.reason,
                estado='SIN_DESTINATARIOS_VALIDOS',
            )

        attempts = []
        for email in recipients.emails:
            attempt = self._deliver(
                self.email_client,
                confirmed_payload,
                email,
                ident,
                alert.sesion_id,
                backup=False,
            )
            attempts.append(attempt)

        primary_successes = sum(attempt.exitoso for attempt in attempts)
        primary_failures = len(attempts) - primary_successes

        if primary_failures > 0 and backup_enabled:
            backup_attempt = self._deliver(
                self.backup_email_client,
                confirmed_payload,
                backup_email,
                ident,
                alert.sesion_id,
                backup=True,
            )
            attempts.append(backup_attempt)

        total_successes = sum(attempt.exitoso for attempt in attempts)
        if primary_failures == 0:
            status = 'EXITO_TOTAL'
        elif total_successes > 0:
            status = 'FALLO_PARCIAL'
        else:
            status = 'FALLO_TOTAL'

        return NotificationResult(
            ident,
            bool(total_successes),
            canal_exitoso='email' if total_successes else None,
            intentos=attempts,
            estado=status,
        )
