"""Catálogo Smile y asociación explícita con PCs; ninguna sala nace del nombre del PC."""
import hashlib
import json
import re
import unicodedata

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from backend.apps.capture.models import AgentRegistration
from backend.apps.capture.storage import FragmentError
from backend.apps.operational.models import OperationalConfiguration, SmileFormat
from .models import AgendaCollection, SmileRoom, SmileCatalogState


def configured_source(identity, source):
    profile = OperationalConfiguration.objects.select_related("smile_collector").filter(pk=1).first()
    if profile and profile.smile_collector_id and source == profile.smile_source:
        agent = profile.smile_collector
        if (not agent.is_active or str(agent.pk) != identity.registry_id or agent.box != identity.box):
            raise FragmentError('AGENDA_SCOPE_FORBIDDEN', 403)
        return {"collector_id": str(agent.pk), "legacy_id": agent.legacy_agent_id,
                "boxes": profile.smile_boxes, "format": profile.smile_format, "profile_revision": profile.smile_revision}
    config = profile.smile_legacy_sources.get(source) if profile else None
    if not config:
        raise FragmentError('AGENDA_SCOPE_FORBIDDEN', 403)
    adopted = (getattr(identity, 'managed', False) and AgentRegistration.objects.filter(
        pk=identity.registry_id, legacy_agent_id=config['collector_id'], box=identity.box,
    ).exists())
    if config['collector_id'] != identity.agent_id and not adopted:
        legacy = settings.CAPTURE_AGENTS.get(config['collector_id'])
        replacement = (getattr(identity, 'managed', False) and legacy and legacy['box'] == identity.box
            and AgentRegistration.objects.filter(pk=identity.registry_id, smile_room__source=source, box=identity.box).exists())
        if not replacement:
            raise FragmentError('AGENDA_SCOPE_FORBIDDEN', 403)
    return config


def source_scope(identity, source):
    config = configured_source(identity, source)
    if not SmileCatalogState.objects.filter(pk=source).exists():
        return {**config, 'room_mapping': {}}
    rooms = list(SmileRoom.objects.filter(source=source, available=True))
    assigned = set(AgentRegistration.objects.filter(smile_room__source=source).values_list('box', flat=True))
    authorized = set(config['boxes'])
    if config.get("format") != SmileFormat.EXCEL:
        authorized.update(assigned)
    mapping = {room.box: room.smile_box_id for room in rooms if room.box in authorized}
    return {**config, 'boxes': sorted(mapping, key=lambda box: int(box[4:])), 'room_mapping': mapping}


def descriptor(collection):
    return {'collection_id': str(collection.collection_id), 'generation': collection.pk, 'source': collection.source,
            'boxes': collection.scope['boxes'], 'formats': ([collection.scope['format']] if 'format' in collection.scope
                                                           else ['smile.excel.v1', 'smile.json.v1']),
            'catalogue_supported': True, 'room_mapping': collection.scope.get('room_mapping', {})}


def validate_rooms(rooms):
    if not isinstance(rooms, list) or not 1 <= len(rooms) <= 500:
        raise FragmentError('SMILE_CATALOG_INVALID', 400)
    seen_boxes, seen_ids, result = set(), set(), []
    for room in rooms:
        if not isinstance(room, dict) or set(room) != {'box', 'name', 'smile_box_id'}:
            raise FragmentError('SMILE_CATALOG_INVALID', 400)
        name, external, box = room['name'], room['smile_box_id'], room['box']
        if (not isinstance(name, str) or len(name) > 100 or not isinstance(external, str)
                or not re.fullmatch(r'[1-9][0-9]{0,11}', external)):
            raise FragmentError('SMILE_CATALOG_INVALID', 400)
        label = ''.join(c for c in unicodedata.normalize('NFKD', name) if not unicodedata.combining(c)).upper()
        match = re.fullmatch(r'\s*BOX(?:\s+DE\s+ATENCION)?[ #\-]*([1-9][0-9]{0,11})\s*', label)
        if not match or box != 'box-' + str(int(match[1])) or box in seen_boxes or external in seen_ids:
            raise FragmentError('SMILE_CATALOG_INVALID', 400)
        seen_boxes.add(box); seen_ids.add(external)
        result.append({'box': box, 'name': name.strip(), 'smile_box_id': external})
    return sorted(result, key=lambda room: int(room['box'][4:]))


@transaction.atomic
def publish(identity, data):
    if not isinstance(data, dict) or set(data) != {'version', 'source', 'collection_id', 'rooms'} or data['version'] != '1.0':
        raise FragmentError('SMILE_CATALOG_INVALID', 400)
    source = data['source']
    if not isinstance(source, str):
        raise FragmentError('SMILE_CATALOG_INVALID', 400)
    rooms = validate_rooms(data['rooms'])
    try:
        from uuid import UUID
        collection_id = UUID(data['collection_id'])
    except (ValueError, TypeError, AttributeError):
        raise FragmentError('SMILE_CATALOG_INVALID', 400) from None
    from backend.apps.capture.pairing import registration_lock
    registration_lock()
    config = configured_source(identity, source)
    collection = AgendaCollection.objects.select_for_update().filter(
        collection_id=collection_id, source=source, agent_id__in=collector_ids(identity, source)).first()
    if collection is None:
        raise FragmentError('AGENDA_COLLECTION_NOT_FOUND', 404)
    if collection.scope.get("profile_revision") != config.get("profile_revision"):
        raise FragmentError("AGENDA_CONFIGURATION_CHANGED", 409)
    digest = hashlib.sha256(json.dumps(rooms, sort_keys=True).encode()).hexdigest()
    state, _ = SmileCatalogState.objects.get_or_create(source=source)
    state = SmileCatalogState.objects.select_for_update().get(pk=source)
    if collection.pk < state.generation:
        raise FragmentError('SMILE_CATALOG_STALE', 409)
    if collection.pk == state.generation:
        if digest != state.digest:
            raise FragmentError('SMILE_CATALOG_CONFLICT', 409)
        return descriptor(collection)
    if collection.received_at:
        raise FragmentError('SMILE_CATALOG_CONFLICT', 409)
    # No cambiar identidades ni reasignar un box si Smile devuelve IDs distintos.
    for item in rooms:
        by_id = SmileRoom.objects.filter(source=source, smile_box_id=item['smile_box_id']).first()
        by_box = SmileRoom.objects.filter(box=item['box']).first()
        if ((by_id and by_id.box != item['box']) or
                (by_box and (by_box.source != source or by_box.smile_box_id != item['smile_box_id']))):
            raise FragmentError('SMILE_CATALOG_CONFLICT', 409)
    now = timezone.now()
    SmileRoom.objects.filter(source=source).update(available=False)
    for item in rooms:
        SmileRoom.objects.update_or_create(source=source, smile_box_id=item['smile_box_id'], defaults={
            'box': item['box'], 'name': item['name'], 'available': True, 'last_seen_at': now,
        })
    state.generation, state.digest, state.synced_at = collection.pk, digest, now
    state.save()
    scope = source_scope(identity, source)
    collection.scope.update(boxes=scope['boxes'], room_mapping=scope['room_mapping'])
    collection.save(update_fields=['scope'])
    return descriptor(collection)


def collector_ids(identity, source):
    config = configured_source(identity, source)
    return {identity.agent_id, config['collector_id'], config.get('legacy_id')} - {None}
