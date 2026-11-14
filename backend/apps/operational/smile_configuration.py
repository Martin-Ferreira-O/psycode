from django.utils import timezone

from backend.apps.capture.models import AgentRegistration, RuntimeLease
from .models import OperationalConfiguration, SMILE_FIELDS, SMILE_TIMEZONE

CAPABILITY = "agenda.smile-config.v1"


def collector_options():
    leases = dict(RuntimeLease.objects.filter(
        name__startswith="control:", expires_at__gt=timezone.now(),
    ).values_list("name", "owner"))
    return [
        {"id": str(agent.pk), "name": agent.name, "box": agent.box,
         "smile_config_supported": (agent.diagnostics or {}).get("smile_config_supported") is True,
         "connected": bool(agent.control_owner and leases.get(f"control:{agent.box}") == agent.control_owner)}
        for agent in AgentRegistration.objects.exclude(token_sha256="").filter(revoked_at__isnull=True).order_by("box", "name")
        if agent.is_active
    ]


def agent_profile(identity):
    config = OperationalConfiguration.objects.select_related("smile_collector").filter(pk=1).first()
    if (config is None or config.smile_collector_id is None or not config.smile_url
            or str(config.smile_collector_id) != identity.registry_id
            or config.smile_collector.box != identity.box or not config.smile_collector.is_active):
        return None
    profile = {
        field.removeprefix("smile_"): getattr(config, field)
        for field in SMILE_FIELDS if field not in {"smile_collector_id", "smile_boxes"}
    }
    return {"revision": config.smile_revision, "timezone": SMILE_TIMEZONE, **profile}
