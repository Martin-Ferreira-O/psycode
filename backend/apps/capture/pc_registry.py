import hashlib
import secrets

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import AgentRegistration


def _generate_credential(agent_id):
    token = f"{agent_id}.{secrets.token_urlsafe(32)}"
    return token, hashlib.sha256(token.encode("ascii")).hexdigest()


@transaction.atomic
def create_agent(*, name, box):
    from .pairing import check_available_box, discard_abandoned_enrollments
    discard_abandoned_enrollments()
    check_available_box(box)
    agent = AgentRegistration(name=name, box=box)
    token, agent.token_sha256 = _generate_credential(agent.agent_id)
    agent.save()
    return agent, token


def _invalidate_connection(agent, cause):
    from .authentication import AgentIdentity
    from . import leases
    from .server_connectivity import register_server_disconnect

    if agent.control_owner is not None:
        name = f"control:{agent.box}"
        if leases.owned(name, agent.control_owner):
            register_server_disconnect(AgentIdentity(str(agent.pk), agent.box, managed=True), cause=cause)
        leases.release(name, agent.control_owner)
    agent.control_owner = None


@transaction.atomic
def revoke_agent(agent):
    from .models import PCPairingCode
    from .pairing import registration_lock
    registration_lock()
    current = get_object_or_404(AgentRegistration.objects.select_for_update(), pk=agent.pk)
    PCPairingCode.objects.filter(agent=current).delete()
    _invalidate_connection(current, "CREDENTIAL_REVOKED")
    current.legacy_enabled = False
    current.revoked_at = current.revoked_at or timezone.now()
    current.save(update_fields=["revoked_at", "control_owner", "legacy_enabled", "updated_at"])
    agent.revoked_at, agent.control_owner = current.revoked_at, None
    return agent


@transaction.atomic
def renew_agent(agent):
    from .models import PCPairingCode
    from .pairing import registration_lock
    registration_lock()
    current = get_object_or_404(AgentRegistration.objects.select_for_update(), pk=agent.pk)
    PCPairingCode.objects.filter(agent=current).delete()
    _invalidate_connection(current, "CREDENTIAL_RENEWED")
    current.legacy_enabled = False
    token, current.token_sha256 = _generate_credential(current.agent_id)
    current.revoked_at = None
    current.save(update_fields=["token_sha256", "revoked_at", "control_owner", "legacy_enabled", "updated_at"])
    agent.token_sha256, agent.revoked_at, agent.control_owner = current.token_sha256, None, None
    return agent, token


def revoke_credential(agent):
    revoke_agent(agent)


def renew_credential(agent):
    return renew_agent(agent)[1]
