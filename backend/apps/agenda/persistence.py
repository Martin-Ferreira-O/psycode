"""Fuente SQL compartida. Solo revisiones completas y válidas actualizan ocupación."""
import hashlib
import io
import json
import re
from datetime import date, timedelta
from zipfile import ZipFile, BadZipFile
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from backend.apps.capture.protocol import identifier, instant
from backend.apps.capture.storage import FragmentError
from .models import AgendaBoxRevision, AgendaCollection
from .services import AgendaService, Appointment, AgendaError

MAX_REPORT_BYTES = 10 * 1024 * 1024


def source_for(identity, source):
    from .catalogue import source_scope
    return source_scope(identity, source)


@transaction.atomic
def issue(identity, source, *, revision=None):
    from .catalogue import descriptor
    from backend.apps.capture.pairing import registration_lock
    registration_lock()
    scope = source_for(identity, source)
    if scope.get("profile_revision") != revision:
        raise FragmentError("AGENDA_CONFIGURATION_CHANGED", 409)
    row = AgendaCollection.objects.create(source=source, agent_id=identity.agent_id,
        scope={key: scope[key] for key in ("boxes", "room_mapping", "profile_revision", "format") if key in scope})
    return descriptor(row)


def receive(identity, metadata, upload):
    required = {"collection_id", "source", "agenda_date", "obtained_at", "boxes", "format_version", "checksum", "outcome"}
    if not isinstance(metadata, dict) or set(metadata) != required:
        raise FragmentError("VALIDATION_ERROR", 400)
    m = metadata
    scope = source_for(identity, m["source"])
    try:
        identifier(m["collection_id"])
        from .catalogue import collector_ids
        issued = AgendaCollection.objects.filter(collection_id=m["collection_id"], source=m["source"], agent_id__in=collector_ids(identity, m["source"])).first()
        if issued is not None and issued.scope:
            scope = issued.scope
        elif issued is not None:
            # Colecciones anteriores a la migración: conservar el contrato legacy,
            # aunque el catálogo recién descubierto tenga otros IDs externos.
            from .catalogue import configured_source
            scope = {**configured_source(identity, m["source"]), "room_mapping": {}}
        date.fromisoformat(m["agenda_date"])
        obtained = instant(m["obtained_at"])
        if obtained > timezone.now() + timedelta(seconds=60):
            raise ValueError()
        if (m["format_version"] not in {"smile.excel.v1", "smile.json.v1"} or m["outcome"] not in {"valid", "partial", "failed"}
                or ("format" in scope and m["format_version"] != scope["format"])
                or not isinstance(m["boxes"], list) or not m["boxes"]
                or len(set(m["boxes"])) != len(m["boxes"]) or set(m["boxes"]) - set(scope["boxes"])
                or not isinstance(m["checksum"], str) or not re.fullmatch(r"[0-9a-f]{64}", m["checksum"])):
            raise ValueError()
    except (ValueError, TypeError):
        raise FragmentError("VALIDATION_ERROR", 400) from None
    raw = upload.read(MAX_REPORT_BYTES + 1)
    if len(raw) > MAX_REPORT_BYTES:
        raise FragmentError("FRAGMENT_TOO_LARGE", 413)
    if hashlib.sha256(raw).hexdigest() != m["checksum"]:
        raise FragmentError("CHECKSUM_MISMATCH", 422)
    agenda = AgendaService()
    if m["outcome"] == "valid":
        try:
            if m["format_version"] == "smile.json.v1":
                result = agenda.load_smile_json(raw, boxes=m["boxes"], agenda_date=m["agenda_date"], smile_ids=scope.get("room_mapping") or None)
            else:
                with ZipFile(io.BytesIO(raw)) as archive:
                    if sum(f.file_size for f in archive.infolist()) > 50 * 1024 * 1024 or len(archive.infolist()) > 1000:
                        raise ValueError()
                result = agenda.load_excel(io.BytesIO(raw))
                if any(appointment.fecha != date.fromisoformat(m["agenda_date"])
                       for appointment in agenda.records):
                    raise ValueError()
            if result.rechazadas or set(result.boxes_actualizados) != set(m["boxes"]):
                raise ValueError()
        except (AgendaError, BadZipFile, ValueError):
            raise FragmentError("AGENDA_REPORT_INVALID", 422) from None
    with transaction.atomic(durable=True):
        from backend.apps.capture.pairing import registration_lock
        from .catalogue import configured_source
        registration_lock()
        config = configured_source(identity, m["source"])
        row = AgendaCollection.objects.select_for_update().filter(
            collection_id=m["collection_id"], source=m["source"], agent_id__in=collector_ids(identity, m["source"])).first()
        if row is None:
            raise FragmentError("AGENDA_COLLECTION_NOT_FOUND", 404)
        if issued is not None and row.scope != issued.scope:
            raise FragmentError("AGENDA_REPORT_CONFLICT", 409)
        if row.received_at is not None:
            if row.metadata != m:
                raise FragmentError("AGENDA_REPORT_CONFLICT", 409)
            return {"collection_id": str(row.collection_id), "generation": row.pk, "outcome": row.outcome}, False
        if row.scope.get("profile_revision") != config.get("profile_revision"):
            raise FragmentError("AGENDA_CONFIGURATION_CHANGED", 409)
        if m["outcome"] == "valid":
            for box in sorted(m["boxes"]):
                previous = AgendaBoxRevision.objects.select_for_update().filter(box=box).first()
                if previous and previous.collection_id > row.pk:
                    raise FragmentError("AGENDA_REPORT_STALE", 409)
            for box in sorted(m["boxes"]):
                records = [{"inicio": a.inicio.isoformat(), "termino": a.termino.isoformat(), "estatus": a.estatus}
                           for a in agenda.records if a.box == box]
                AgendaBoxRevision.objects.update_or_create(box=box, defaults={"collection": row, "appointments": records})
        row.metadata, row.checksum, row.report = m, m["checksum"], raw
        row.outcome, row.received_at = m["outcome"], timezone.now()
        row.save()
        return {"collection_id": str(row.collection_id), "generation": row.pk, "outcome": row.outcome}, True


def refresh(agenda):
    by_box = {}
    for revision in AgendaBoxRevision.objects.all():
        by_box[revision.box] = [Appointment(revision.box, instant(a["inicio"]),
            instant(a["termino"]) - instant(a["inicio"]), instant(a["termino"]), a["estatus"])
            for a in revision.appointments]
    agenda.replace_boxes(by_box)
    return agenda
