"""Formato estable de salas; su número no está limitado al despliegue inicial."""
import re

BOX_PATTERN = r"box-[1-9][0-9]{0,11}"
DEFAULT_PC_BOXES = tuple(f"box-{number}" for number in range(3, 8))


def is_box(value):
    return isinstance(value, str) and re.fullmatch(BOX_PATTERN, value) is not None


def known_boxes():
    """Salas reales del registro, agenda y configuración; sin un catálogo fijo implícito."""
    from django.conf import settings
    from backend.apps.capture.models import AgentRegistration, CaptureSession
    from backend.apps.agenda.models import AgendaBoxRevision
    boxes = set()
    boxes.update(item['box'] for item in settings.CAPTURE_AGENTS.values())
    for scope in settings.CAPTURE_AGENDA_SOURCES.values():
        boxes.update(scope['boxes'])
    for model in (AgentRegistration, CaptureSession, AgendaBoxRevision):
        boxes.update(model.objects.values_list('box', flat=True).distinct())
    return sorted((box for box in boxes if is_box(box)), key=lambda box: int(box[4:]))


def registrable_boxes():
    """Boxes del registro administrativo; no crean salas ni autorizan captura."""
    from django.conf import settings
    boxes = set(getattr(settings, 'PC_REGISTRY_BOXES', DEFAULT_PC_BOXES))
    boxes.update(known_boxes())
    return sorted(boxes, key=lambda box: int(box[4:]))
