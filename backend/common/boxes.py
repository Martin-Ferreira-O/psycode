import re

BOX_PATTERN = r"box-[1-9][0-9]{0,11}"
DEFAULT_PC_BOXES = tuple(f"box-{number}" for number in range(3, 8))


def is_box(value):
    return isinstance(value, str) and re.fullmatch(BOX_PATTERN, value) is not None


def known_boxes():
    from django.conf import settings
    from backend.apps.capture.models import AgentRegistration, CaptureSession
    from backend.apps.agenda.models import AgendaBoxRevision
    from backend.apps.operational.models import OperationalConfiguration
    boxes = set()
    boxes.update(item['box'] for item in settings.CAPTURE_AGENTS.values())
    config = OperationalConfiguration.objects.filter(pk=1).first()
    if config:
        boxes.update(config.smile_boxes)
        for scope in config.smile_legacy_sources.values():
            boxes.update(scope['boxes'])
    for model in (AgentRegistration, CaptureSession, AgendaBoxRevision):
        boxes.update(model.objects.values_list('box', flat=True).distinct())
    return sorted((box for box in boxes if is_box(box)), key=lambda box: int(box[4:]))


def registrable_boxes():
    from django.conf import settings
    boxes = set(getattr(settings, 'PC_REGISTRY_BOXES', DEFAULT_PC_BOXES))
    boxes.update(known_boxes())
    return sorted(boxes, key=lambda box: int(box[4:]))
