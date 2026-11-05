"""Outbox SQL idempotente para bitácora Mongo; se conserva si Mongo cae."""
from django.utils import timezone

from backend.apps.alerts.repositories import AlertsRepository
from backend.common.audit import AuditWriter
from .models import StorageCleanupRun


def flush_storage_audit(collection=None):
    sent = 0
    for run in StorageCleanupRun.objects.filter(finished_at__isnull=False, audit_sent_at__isnull=True).order_by("started_at")[:100]:
        event = {
            "event_id": str(run.pk), "timestamp": run.finished_at,
            "action": "storage.cleanup", "outcome": "success" if run.outcome == "success" else "failure",
            "actor": "Sistema" if run.actor_id is None else "Usuario",
            "actor_id": str(run.actor_id) if run.actor_id else None,
            "alerta_id": None, "sesion_id": None, "sequence": None,
            "channel": None, "contingencia": None, "motivo": None,
            "error_code": run.error_code or ("STORAGE_DELETE_FAILED" if run.failures else None),
            "duration_ms": max(0, int((run.finished_at - run.started_at).total_seconds() * 1000)),
            "intentos": [],
            "storage": {name: getattr(run, name) for name in ("source", "freed_bytes", "removed", "failures", "protected", "checkpoints", "provider_deleted", "provider_failures")},
        }
        AuditWriter.emit(event)
        try:
            if collection is None:
                repository = AlertsRepository()
                repository.ensure_schema()
                events = repository._events()
            else:
                events = collection
            events.update_one({"event_id": event["event_id"]}, {"$setOnInsert": event}, upsert=True)
            StorageCleanupRun.objects.filter(pk=run.pk).update(audit_sent_at=timezone.now())
            sent += 1
        except Exception:
            break  # Un reinicio repite el mismo UUID, nunca pierde ni duplica el evento.
    return sent
