"""Bitácora compartida de alertas. Solo metadatos estructurados permitidos."""
import logging
from uuid import UUID, uuid4

from django.utils import timezone

from backend.common.audit import AuditWriter

ACTIONS = ("alerts.register", "alerts.evaluate", "notifications.send",
           "analysis.speechmatics", "analysis.jev", "alerts.flow")
OUTCOMES = ("success", "failure", "skipped")
ERROR_CODES = frozenset({
    "SPEECHMATICS_FAILED", "SPEECHMATICS_DELETE_PENDING", "JEV_FAILED",
    "JEV_SUBMISSION_UNCERTAIN", "FLOW_INTERRUPTED", "ALERT_PERSISTENCE_FAILED",
    "NOTIFICATION_TIMEOUT", "NOTIFICATION_CONNECTION_FAILED", "NOTIFICATION_REJECTED",
    "NOTIFICATION_NOT_CONFIGURED", "NOTIFICATION_INTERNAL_ERROR",
})


class AlertAudit:
    def __init__(self, events):
        self.events = events

    def record(self, action, outcome, *, alerta_id=None, actor_id=None, sesion_id=None,
               sequence=None, channel=None, backup=None, error_code=None, duration_ms=None):
        if action not in ACTIONS or outcome not in OUTCOMES:
            raise ValueError("Evento de bitácora inválido")
        if error_code is not None and error_code not in ERROR_CODES:
            raise ValueError("Código técnico no permitido")
        if channel not in (None, "email", "teams"):
            raise ValueError("Canal inválido")
        if sequence is not None and (type(sequence) is not int or sequence < 0):
            raise ValueError("Secuencia inválida")
        event = {
            "event_id": str(uuid4()), "timestamp": timezone.now(),
            "action": action, "outcome": outcome,
            "actor": "Sistema" if actor_id is None else "Usuario",
            "actor_id": None if actor_id is None else str(UUID(str(actor_id))),
            "alerta_id": None if alerta_id is None else str(UUID(str(alerta_id))),
            "sesion_id": None if sesion_id is None else str(UUID(str(sesion_id))),
            "sequence": sequence, "channel": channel, "contingencia": backup,
            "motivo": None, "error_code": error_code,
            "duration_ms": None if duration_ms is None else max(0, round(duration_ms)),
            "intentos": [],
        }
        AuditWriter.emit(event)
        try:
            self.events().insert_one(event.copy())
        except Exception:
            # El evento original conserva su event_id en el logger si MongoDB cae.
            logging.getLogger("psycode.audit").error(
                'audit_events.write failure event_id=%s error_code=AUDIT_UNAVAILABLE', event["event_id"])
        return event
