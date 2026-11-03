"""Auditoría con lista permitida: nunca aceptar cuerpos, emails ni tokens."""
import json
import logging
import uuid

from django.utils import timezone


class AuditWriter:
    @staticmethod
    def record(action, outcome, *, actor_id=None, error_code=None, alerta_id=None):
        event = {"event_id": str(uuid.uuid4()), "timestamp": timezone.now().isoformat(), "action": action, "outcome": outcome}
        if actor_id is not None:
            event["actor_id"] = str(actor_id)
        if alerta_id is not None:
            event["alerta_id"] = str(alerta_id)
        if error_code:
            event["error_code"] = error_code
        AuditWriter.emit(event)
        return event

    @staticmethod
    def emit(event):
        logging.getLogger("psycode.audit").info(json.dumps(event, default=lambda value: value.isoformat()))
