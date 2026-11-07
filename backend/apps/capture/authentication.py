"""Identidades de agentes por box, sin sesiones ni permisos de profesionales."""

import hashlib
import hmac
import re
from dataclasses import dataclass
from uuid import UUID

from django.conf import settings
from rest_framework.authentication import (
    BaseAuthentication,
    get_authorization_header,
)
from rest_framework.exceptions import AuthenticationFailed

from backend.apps.accounts.rate_limits import consume_auth_attempt

from .models import AgentRegistration


@dataclass(frozen=True)
class AgentIdentity:
    agent_id: str
    box: str
    is_authenticated: bool = True

    # True cuando el PC proviene del registro administrable en BD.
    managed: bool = False

    # Huella de la credencial con la que abrió la conexión.
    # Permite detectar renovación/revocación en conexiones WSS activas.
    credential_hash: str = ""


class BoxAgentAuthentication(BaseAuthentication):
    def authenticate(self, request):
        header = get_authorization_header(request)

        if not header:
            return None

        identity = authenticate_agent_header(
            header,
            source_ip=request.META.get(
                "REMOTE_ADDR",
                "",
            ),
        )

        return identity, None

    def authenticate_header(self, request):
        return "Agent"


def _managed_registration(agent_id):
    """
    Busca un PC administrado en BD.

    Los agentes antiguos pueden tener IDs que no son UUID,
    por eso un ID legacy inválido como UUID simplemente continúa
    hacia CAPTURE_AGENTS.
    """
    try:
        key = UUID(agent_id)
    except (TypeError, ValueError, AttributeError):
        return None

    return (
        AgentRegistration.objects
        .filter(pk=key)
        .only(
            "agent_id",
            "box",
            "token_sha256",
            "revoked_at",
        )
        .first()
    )


def _consume_failed_agent_auth(*, agent_id="", source_ip=""):
    """
    Consume presupuesto de intentos fallidos de autenticación.

    Se limita tanto por IP como por identidad del agente.
    Las identidades se almacenan mediante hash en AuthRateLimit.
    """
    identity = agent_id or "malformed"

    if source_ip:
        consume_auth_attempt(
            "capture.agent.ip",
            source_ip,
            limit=settings.CAPTURE_AGENT_AUTH_IP_LIMIT,
            seconds=settings.CAPTURE_AGENT_AUTH_WINDOW_SECONDS,
        )

    consume_auth_attempt(
        "capture.agent.id",
        identity,
        limit=settings.CAPTURE_AGENT_AUTH_ID_LIMIT,
        seconds=settings.CAPTURE_AGENT_AUTH_WINDOW_SECONDS,
    )


def authenticate_agent_header(header, *, source_ip=""):
    """Mismas reglas de identidad para HTTP y handshake WebSocket."""

    try:
        scheme, token = header.decode("ascii").split()
        agent_id, secret = token.split(".")
    except (UnicodeError, ValueError):
        _consume_failed_agent_auth(
            source_ip=source_ip,
        )
        raise AuthenticationFailed() from None

    if (
        scheme.lower() != "agent"
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", agent_id)
        or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", secret)
    ):
        _consume_failed_agent_auth(
            agent_id=agent_id,
            source_ip=source_ip,
        )
        raise AuthenticationFailed()

    token_hash = hashlib.sha256(
        token.encode("ascii")
    ).hexdigest()

    # 1. PCs creados desde Gestión de PCs.
    registration = _managed_registration(agent_id)

    if registration is not None:
        matches = hmac.compare_digest(
            token_hash,
            registration.token_sha256,
        )

        if registration.revoked_at is not None or not matches:
            _consume_failed_agent_auth(
                agent_id=agent_id,
                source_ip=source_ip,
            )
            raise AuthenticationFailed()

        return AgentIdentity(
            agent_id,
            registration.box,
            managed=True,
            credential_hash=token_hash,
        )

    # 2. Compatibilidad con PCs antiguos configurados
    # mediante CAPTURE_AGENTS.
    credential = settings.CAPTURE_AGENTS.get(agent_id)

    expected = (
        credential["token_sha256"]
        if credential
        else "0" * 64
    )

    matches = hmac.compare_digest(
        token_hash,
        expected,
    )

    if not credential or not matches:
        _consume_failed_agent_auth(
            agent_id=agent_id,
            source_ip=source_ip,
        )
        raise AuthenticationFailed()

    return AgentIdentity(
        agent_id,
        credential["box"],
        credential_hash=token_hash,
    )


def ensure_agent_identity_current(identity):
    """
    Comprueba que una conexión administrada siga siendo válida.

    Una revocación, renovación de credencial o cambio de box
    invalida la conexión que utilizaba la credencial anterior.
    """

    if not identity.managed:
        return

    registration = _managed_registration(
        identity.agent_id
    )

    if (
        registration is None
        or registration.revoked_at is not None
        or registration.box != identity.box
        or not hmac.compare_digest(
            registration.token_sha256,
            identity.credential_hash,
        )
    ):
        raise AuthenticationFailed()
    