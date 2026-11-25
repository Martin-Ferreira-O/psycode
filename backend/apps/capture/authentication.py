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
    managed: bool = False
    credential_hash: str = ""
    registration_id: str = ""

    @property
    def registry_id(self):
        return self.registration_id or self.agent_id


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
            "legacy_agent_id",
            "legacy_enabled",
        )
        .first()
    )


def _consume_failed_agent_auth(*, agent_id="", source_ip=""):
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


    registration = _managed_registration(agent_id)

    if registration is not None:
        matches = hmac.compare_digest(
            token_hash,
            registration.token_sha256,
        )

        if not registration.is_active or not matches:
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
    from .legacy_registry import sync_legacy_registry
    if agent_id in settings.CAPTURE_AGENTS:
        sync_legacy_registry()
    registration = AgentRegistration.objects.filter(legacy_agent_id=agent_id).first()
    matches = hmac.compare_digest(token_hash, registration.token_sha256 if registration else "0" * 64)
    if (registration is None or not registration.legacy_enabled
            or not registration.is_active or not matches or _legacy_replaced(registration.box)
            or not _legacy_credential_current(agent_id, registration.box, token_hash)):
        _consume_failed_agent_auth(agent_id=agent_id, source_ip=source_ip)
        raise AuthenticationFailed()
    return AgentIdentity(agent_id, registration.box, managed=True, credential_hash=token_hash, registration_id=str(registration.pk))


def ensure_agent_identity_current(identity):
    if identity.registration_id and not _legacy_credential_current(identity.agent_id, identity.box, identity.credential_hash):
        raise AuthenticationFailed()
    if not identity.managed:
        registration = AgentRegistration.objects.filter(legacy_agent_id=identity.agent_id).first()
        if (_legacy_replaced(identity.box) or (registration and (
                not registration.legacy_enabled or not registration.is_active
                or (identity.credential_hash and not hmac.compare_digest(identity.credential_hash, registration.token_sha256))))):
            raise AuthenticationFailed()
        return

    registration = _managed_registration(
        identity.registry_id
    )

    if (
        registration is None
        or not registration.is_active
        or registration.box != identity.box
        or not hmac.compare_digest(
            registration.token_sha256,
            identity.credential_hash,
        )
    ):
        raise AuthenticationFailed()


def _legacy_replaced(box):
    from backend.apps.agenda.models import SmileRoom
    return SmileRoom.objects.filter(box=box, legacy_blocked_at__isnull=False).exists()


def _legacy_credential_current(agent_id, box, token_hash):
    configured = settings.CAPTURE_AGENTS.get(agent_id)
    return bool(configured and configured['box'] == box and hmac.compare_digest(configured['token_sha256'], token_hash))
