from django.db import transaction
from django.utils import timezone

from .models import AgentRegistration, ServerConnectivityOutage


@transaction.atomic
def register_server_disconnect(identity, *, cause="UNKNOWN"):
    if not getattr(identity, "managed", False):
        return None
    agent = AgentRegistration.objects.select_for_update().filter(pk=identity.registry_id).first()
    if agent is None:
        return None
    existing = agent.server_connectivity_outages.filter(recovered_at__isnull=True).first()
    if existing is not None:
        return existing
    return ServerConnectivityOutage.objects.create(
        agent=agent, box=identity.box, started_at=agent.last_seen_at,
        start_time_quality="estimated" if agent.last_seen_at else "unknown",
        recovery_time_quality="unknown", cause=cause or "UNKNOWN",
    )


@transaction.atomic
def register_server_reconnect(identity):
    if not getattr(identity, "managed", False):
        return None
    agent = AgentRegistration.objects.select_for_update().filter(pk=identity.registry_id).first()
    if agent is None:
        return None
    outage = agent.server_connectivity_outages.filter(recovered_at__isnull=True).first()
    if outage is None:
        return None
    now = timezone.now()
    outage.recovered_at = outage.recovery_detected_at = now
    outage.recovery_time_quality = "estimated"
    outage.save(update_fields=["recovered_at", "recovery_detected_at", "recovery_time_quality", "updated_at"])
    return outage


@transaction.atomic
def reconcile_connection(agent):
    from .authentication import AgentIdentity
    from . import leases

    current = AgentRegistration.objects.select_for_update().get(pk=agent.pk)
    if current.control_owner and not leases.owned(f"control:{current.box}", current.control_owner):
        register_server_disconnect(AgentIdentity(str(current.pk), current.box, managed=True))
        current.control_owner = None
        current.save(update_fields=["control_owner"])
        agent.control_owner = None
