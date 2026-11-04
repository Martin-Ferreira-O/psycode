"""Bitácora compartida de alertas. Solo metadatos estructurados permitidos."""
import logging
from uuid import UUID, uuid4

from django.utils import timezone

from backend.common.audit import AuditWriter

ACTIONS = ("alerts.register", "alerts.evaluate", "notifications.send", "notifications.result",
           "analysis.speechmatics", "analysis.jev", "alerts.flow")
OUTCOMES = ("success", "failure", "skipped")
ERROR_CODES = frozenset({
    "SPEECHMATICS_FAILED", "SPEECHMATICS_DELETE_PENDING", "JEV_FAILED",
    "SPEECHMATICS_UNCERTAIN", "ANALYSIS_CONTEXT_LOST", "NOTIFICATION_UNCERTAIN",
    "JEV_SUBMISSION_UNCERTAIN", "FLOW_INTERRUPTED", "ALERT_PERSISTENCE_FAILED",
    "NOTIFICATION_TIMEOUT", "NOTIFICATION_CONNECTION_FAILED", "NOTIFICATION_REJECTED",
    "NOTIFICATION_NOT_CONFIGURED", "NOTIFICATION_INTERNAL_ERROR",
})


NOTIFICATION_MODES = ("lista_distribucion", "supervisores_activos")
NOTIFICATION_STATUSES = ("EXITO_TOTAL", "FALLO_PARCIAL", "FALLO_TOTAL", "SIN_DESTINATARIOS_VALIDOS")
NOTIFICATION_REASONS = ("FALLO_PARCIAL", "FALLO_TOTAL", "SIN_DESTINATARIOS_VALIDOS")
NOTIFICATION_COUNTS = ("primary_successes", "primary_failures", "backup_successes", "backup_failures")


def notification_metadata(value, action):
    """Rechaza campos libres antes de emitirlos tanto al logger como a MongoDB."""
    if not isinstance(value, dict):
        raise ValueError("Metadatos de notificación inválidos")
    common = {"id", "mode", "phase", "reason"}
    phase = value.get("phase")
    if action == "notifications.send" and phase in ("principal", "respaldo"):
        expected = common | {"attempt"}
        if type(value.get("attempt")) is not int or value["attempt"] < 1:
            raise ValueError("Número de intento inválido")
    elif action == "notifications.result" and phase == "resumen":
        expected = common | {"status", *NOTIFICATION_COUNTS}
        if value.get("status") not in NOTIFICATION_STATUSES:
            raise ValueError("Resultado de notificación inválido")
        for name in NOTIFICATION_COUNTS:
            if type(value.get(name)) is not int or value[name] < 0:
                raise ValueError("Conteo de notificación inválido")
    else:
        raise ValueError("Fase de notificación inválida")
    if set(value) != expected:
        raise ValueError("Campos de notificación no permitidos")
    if value["mode"] is not None and value["mode"] not in NOTIFICATION_MODES:
        raise ValueError("Modalidad de notificación inválida")
    if value["reason"] is not None and value["reason"] not in NOTIFICATION_REASONS:
        raise ValueError("Motivo de notificación inválido")
    return dict(value, id=str(UUID(str(value["id"]))))


class AlertAudit:
    def __init__(self, events):
        self.events = events

    def record(self, action, outcome, *, alerta_id=None, actor_id=None, sesion_id=None,
               sequence=None, channel=None, backup=None, error_code=None, duration_ms=None,
               notification=None):
        if action not in ACTIONS or outcome not in OUTCOMES:
            raise ValueError("Evento de bitácora inválido")
        if action in ("alerts.register", "alerts.evaluate", "notifications.send", "notifications.result") and alerta_id is None:
            raise ValueError("El evento requiere alerta_id")
        if action == "alerts.evaluate" and actor_id is None:
            raise ValueError("La evaluación requiere usuario responsable")
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
        if notification is not None:
            event["notification"] = notification_metadata(notification, action)
        elif action == "notifications.result":
            raise ValueError("El resumen requiere metadatos de notificación")
        AuditWriter.emit(event)
        try:
            self.events().insert_one(event.copy())
        except Exception:
            # El evento original conserva su event_id en el logger si MongoDB cae.
            logging.getLogger("psycode.audit").error(
                'audit_events.write failure event_id=%s error_code=AUDIT_UNAVAILABLE', event["event_id"])
        return event
