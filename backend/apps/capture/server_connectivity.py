"""Registro de desconexiones inferidas por el servidor."""

from django.db import transaction
from django.utils import timezone

from .models import (
    AgentRegistration,
    AgentStatus,
    ServerConnectivityOutage,
)


def register_server_disconnect(identity, *, cause="UNKNOWN"):
    """
    Registra una caída inferida por Psycode.

    Solo aplica a PCs administrados mediante AgentRegistration.
    No duplica una caída que ya esté abierta.
    """

    if not getattr(identity, "managed", False):
        return None

    try:
        agent = AgentRegistration.objects.get(
            agent_id=identity.agent_id,
        )
    except AgentRegistration.DoesNotExist:
        return None

    # Ya existe una caída abierta para este PC.
    existing = (
        ServerConnectivityOutage.objects
        .filter(
            agent=agent,
            recovered_at__isnull=True,
        )
        .order_by("-detected_at")
        .first()
    )

    if existing is not None:
        return existing

    status = AgentStatus.objects.filter(
        box=identity.box,
    ).first()

    # seen_at es solamente el último instante conocido,
    # por lo que el comienzo de la caída es estimado.
    started_at = (
        status.seen_at
        if status
        else None
    )

    start_quality = (
        ServerConnectivityOutage.TimeQuality.ESTIMATED
        if started_at is not None
        else ServerConnectivityOutage.TimeQuality.UNKNOWN
    )

    return ServerConnectivityOutage.objects.create(
        agent=agent,
        box=identity.box,
        started_at=started_at,
        start_time_quality=start_quality,
        recovery_time_quality=(
            ServerConnectivityOutage.TimeQuality.UNKNOWN
        ),
        cause=cause or "UNKNOWN",
    )


@transaction.atomic
def register_server_reconnect(identity):
    """
    Cierra la última caída inferida abierta cuando el PC
    vuelve a establecer correctamente su conexión WSS.
    """

    if not getattr(identity, "managed", False):
        return None

    try:
        agent = AgentRegistration.objects.get(
            agent_id=identity.agent_id,
        )
    except AgentRegistration.DoesNotExist:
        return None

    outage = (
        ServerConnectivityOutage.objects
        .select_for_update()
        .filter(
            agent=agent,
            recovered_at__isnull=True,
        )
        .order_by("-detected_at")
        .first()
    )

    if outage is None:
        return None

    now = timezone.now()

    outage.recovered_at = now
    outage.recovery_detected_at = now

    # El servidor conoce cuándo observó la reconexión,
    # pero no el instante físico exacto en que volvió la red.
    outage.recovery_time_quality = (
        ServerConnectivityOutage.TimeQuality.ESTIMATED
    )

    outage.save(
        update_fields=[
            "recovered_at",
            "recovery_detected_at",
            "recovery_time_quality",
            "updated_at",
        ]
    )

    return outage