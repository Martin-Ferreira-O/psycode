"""Incorpora identidades existentes sin cambiar claves ni atribuir datos por sala."""
from uuid import UUID

from django.conf import settings
from django.db import transaction

from .models import AgentRegistration


@transaction.atomic
def sync_legacy_registry():
    from .pairing import registration_lock
    registration_lock()
    for identity, configured in settings.CAPTURE_AGENTS.items():
        if AgentRegistration.objects.filter(legacy_agent_id=identity).exists():
            continue  # Nunca reactivar una clave retirada, ni sobrescribir la BD con el entorno.
        try:
            key = UUID(identity)
        except ValueError:
            key = None
        if key:
            existing = AgentRegistration.objects.filter(pk=key).first()
            if existing:
                if (existing.legacy_agent_id is None and existing.box == configured['box']
                        and existing.token_sha256 == configured['token_sha256']):
                    existing.legacy_agent_id, existing.legacy_enabled = identity, existing.is_active
                    existing.save(update_fields=['legacy_agent_id', 'legacy_enabled'])
                continue
        candidates = list(AgentRegistration.objects.filter(
            box=configured['box'], token_sha256=configured['token_sha256'], legacy_agent_id__isnull=True,
        ))
        if len(candidates) == 1:
            agent = candidates[0]
            agent.legacy_agent_id, agent.legacy_enabled = identity, agent.is_active
            agent.save(update_fields=['legacy_agent_id', 'legacy_enabled'])
        else:
            from backend.apps.agenda.models import SmileRoom
            retired = SmileRoom.objects.filter(box=configured['box'], legacy_blocked_at__isnull=False).exists()
            from django.utils import timezone
            AgentRegistration.objects.create(
                name=f"PC {configured['box'].replace('box-', 'Box ')}", box=configured['box'],
                legacy_agent_id=identity, legacy_enabled=not retired,
                token_sha256=configured['token_sha256'], revoked_at=timezone.now() if retired else None,
            )
    from backend.apps.agenda.models import SmileRoom
    for room in SmileRoom.objects.all():
        candidates = list(AgentRegistration.objects.filter(box=room.box))
        if len(candidates) == 1 and not candidates[0].smile_room_id:
            AgentRegistration.objects.filter(pk=candidates[0].pk).update(smile_room=room)


def historical_ids(agent):
    return [str(agent.pk)] + ([agent.legacy_agent_id] if agent.legacy_agent_id else [])
