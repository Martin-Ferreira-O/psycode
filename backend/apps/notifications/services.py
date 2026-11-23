from django.conf import settings

from uuid import uuid4

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

    def _deliver(self, client, payload, email, ident, sesion_id, *, backup: bool,
                 notification, attempt, reason=None) -> AttemptResult:
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
            notification=dict(notification, phase='respaldo' if backup else 'principal',
                              attempt=attempt, reason=reason),
        )
        return sanitized

    def _record_result(self, result, sesion_id, notification, primary, backup, reason=None):
        counts = {
            'primary_successes': sum(item.exitoso for item in primary),
            'primary_failures': sum(not item.exitoso for item in primary),
            'backup_successes': sum(item.exitoso for item in backup),
            'backup_failures': sum(not item.exitoso for item in backup),
        }
        outcome = ('success' if result.estado == 'EXITO_TOTAL' else
                   'skipped' if not result.intentos else 'failure')
        self.audit.record(
            'notifications.result', outcome, alerta_id=result.alerta_id,
            sesion_id=sesion_id, channel='email', backup=bool(backup),
            notification=dict(notification, phase='resumen', status=result.estado,
                              reason=reason, **counts),
        )
        return result

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
            str(alert.semaforo), 'riesgo_suicida', alert.box, alert.fecha_hora.isoformat(),
            es_prueba=alert.es_prueba,
        )
        recipients = self.recipient_resolver.resolve()
        notification = {'id': str(uuid4()), 'mode': (
            recipients.mode if recipients.mode in NotificationMode.values else None)}
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
                    notification=notification, attempt=1, reason='SIN_DESTINATARIOS_VALIDOS',
                )
                status = 'FALLO_PARCIAL' if backup_attempt.exitoso else 'FALLO_TOTAL'
                result = NotificationResult(
                    ident,
                    backup_attempt.exitoso,
                    canal_exitoso='email' if backup_attempt.exitoso else None,
                    intentos=[backup_attempt],
                    estado=status,
                )
                return self._record_result(result, alert.sesion_id, notification, [], [backup_attempt],
                                           reason='SIN_DESTINATARIOS_VALIDOS')
            result = NotificationResult(
                ident,
                False,
                motivo_omision=recipients.reason,
                estado='SIN_DESTINATARIOS_VALIDOS',
            )
            return self._record_result(result, alert.sesion_id, notification, [], [],
                                       reason='SIN_DESTINATARIOS_VALIDOS')

        attempts = []
        for email in recipients.emails:
            attempt = self._deliver(
                self.email_client,
                confirmed_payload,
                email,
                ident,
                alert.sesion_id,
                backup=False,
                notification=notification, attempt=len(attempts) + 1,
            )
            attempts.append(attempt)

        primary_successes = sum(attempt.exitoso for attempt in attempts)
        primary_failures = len(attempts) - primary_successes
        primary_attempts = attempts.copy()
        backup_attempts = []
        failure_reason = ('FALLO_PARCIAL' if primary_successes else 'FALLO_TOTAL') if primary_failures else None

        if primary_failures > 0 and backup_enabled:
            backup_attempt = self._deliver(
                self.backup_email_client,
                confirmed_payload,
                backup_email,
                ident,
                alert.sesion_id,
                backup=True,
                notification=notification, attempt=len(attempts) + 1, reason=failure_reason,
            )
            attempts.append(backup_attempt)
            backup_attempts.append(backup_attempt)

        total_successes = sum(attempt.exitoso for attempt in attempts)
        if primary_failures == 0:
            status = 'EXITO_TOTAL'
        elif total_successes > 0:
            status = 'FALLO_PARCIAL'
        else:
            status = 'FALLO_TOTAL'

        result = NotificationResult(
            ident,
            bool(total_successes),
            canal_exitoso='email' if total_successes else None,
            intentos=attempts,
            estado=status,
        )
        return self._record_result(result, alert.sesion_id, notification, primary_attempts,
                                   backup_attempts, reason=failure_reason)
