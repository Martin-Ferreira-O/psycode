"""Solicitud acotada para el colector designado. No emite una recolección."""
from datetime import timedelta
from uuid import uuid4

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from backend.apps.capture.agent_events import BoundedJSONParser
from backend.apps.capture.authentication import AgentIdentity, BoxAgentAuthentication, ensure_agent_identity_current
from backend.apps.capture.models import AgentRegistration, RuntimeLease
from backend.apps.capture.protocol import identifier
from backend.apps.capture.storage import FragmentError
from backend.common.errors import ServiceError
from backend.common.responses import success_response

from .catalogue import configured_source
from .models import SmileCollectorCheck

CAPABILITY = "agenda.smile-check.v1"
RESULTS = {"ok", "missing_profile", "source_mismatch", "external_command", "timeout", "failed"}


def sources_for(identity):
    sources = []
    for source in settings.CAPTURE_AGENDA_SOURCES:
        try:
            configured_source(identity, source)
        except FragmentError:
            continue
        sources.append(source)
    return sorted(sources)


def identity_for(agent):
    return AgentIdentity(str(agent.pk), agent.box, managed=True)


def snapshot(check, now):
    if check is None:
        return None
    state = check.state
    if state in {"queued", "running"} and check.expires_at <= now:
        state = "expired"
    return {"source": check.source, "state": state, "result": check.result,
            "requested_at": check.requested_at}


@transaction.atomic
def request_check(agent_id, source):
    agent = AgentRegistration.objects.select_for_update().filter(pk=agent_id).first()
    if agent is None:
        raise ServiceError("PC_NOT_FOUND", "No se encontró el PC.", 404)
    if source not in sources_for(identity_for(agent)):
        raise ServiceError("SMILE_CHECK_FORBIDDEN", "Este PC no es el colector de la fuente.", 403)
    now = timezone.now()
    if not (agent.is_active and agent.control_owner and RuntimeLease.objects.filter(
        name=f"control:{agent.box}", owner=agent.control_owner, expires_at__gt=now,
    ).exists()):
        raise ServiceError("SMILE_CHECK_OFFLINE", "El colector no está conectado.", 409)
    if (agent.diagnostics or {}).get("smile_check_supported") is not True:
        raise ServiceError("SMILE_CHECK_UPDATE_REQUIRED", "Actualiza el agente para poder probar el colector.", 409)
    check = SmileCollectorCheck.objects.filter(agent=agent).first()
    previous = snapshot(check, now)
    if previous and previous["state"] in {"queued", "running"}:
        if check.source == source:
            return previous
        raise ServiceError("SMILE_CHECK_BUSY", "Ya hay una prueba en curso en este PC.", 409)
    if check and (now - check.requested_at) < timedelta(seconds=30):
        raise ServiceError("SMILE_CHECK_WAIT", "Espera 30 segundos desde la última solicitud.", 429)
    check, _ = SmileCollectorCheck.objects.update_or_create(agent=agent, defaults={
        "request_id": uuid4(), "source": source, "requested_at": now,
        "expires_at": now + timedelta(minutes=10), "state": "queued", "result": "",
    })
    return snapshot(check, now)


def agent_action(identity, data):
    if not isinstance(data, dict):
        raise FragmentError("VALIDATION_ERROR", 400)
    action = data.get("action")
    if action == "claim" and set(data) == {"action"}:
        if not SmileCollectorCheck.objects.filter(
            agent_id=identity.registry_id, state="queued", expires_at__gt=timezone.now(),
        ).exists():
            return None
        request_id = None
    elif action == "finish" and set(data) == {"action", "request_id", "result"}:
        try:
            request_id = identifier(data["request_id"])
            if not isinstance(data["result"], str) or data["result"] not in RESULTS:
                raise ValueError()
        except (ValueError, TypeError):
            raise FragmentError("VALIDATION_ERROR", 400) from None
    else:
        raise FragmentError("VALIDATION_ERROR", 400)
    with transaction.atomic():
        AgentRegistration.objects.select_for_update().get(pk=identity.registry_id)
        ensure_agent_identity_current(identity)
        check = SmileCollectorCheck.objects.filter(agent_id=identity.registry_id).first()
        now = timezone.now()
        if action == "claim":
            if check is None or check.state != "queued" or check.expires_at <= now:
                return None
            configured_source(identity, check.source)
            check.state = "running"
            check.save(update_fields=["state"])
            return {"request_id": str(check.request_id), "source": check.source}
        if check is None or check.request_id != request_id:
            raise FragmentError("SMILE_CHECK_EXPIRED", 409)
        configured_source(identity, check.source)
        if check.state == "finished" and check.result == data["result"]:
            return {"recorded": True}
        if check.state != "running" or check.expires_at <= now:
            raise FragmentError("SMILE_CHECK_EXPIRED", 409)
        check.state, check.result = "finished", data["result"]
        check.save(update_fields=["state", "result"])
        return {"recorded": True}


class AgentSmileCheckView(APIView):
    authentication_classes = [BoxAgentAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [BoundedJSONParser]

    def post(self, request):
        return success_response(agent_action(request.user, request.data), "Diagnóstico Smile")
