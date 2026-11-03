"""Identidades de agentes por box, sin sesiones ni permisos de profesionales."""
import hashlib
import hmac
import re
from dataclasses import dataclass

from django.conf import settings
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed


@dataclass(frozen=True)
class AgentIdentity:
    agent_id: str
    box: str
    is_authenticated: bool = True


class BoxAgentAuthentication(BaseAuthentication):
    def authenticate(self, request):
        header = get_authorization_header(request)
        if not header:
            return None
        return authenticate_agent_header(header), None

    def authenticate_header(self, request):
        return "Agent"


def authenticate_agent_header(header):
    """Mismas reglas de identidad para HTTP y handshake WebSocket."""
    try:
        scheme, token = header.decode("ascii").split()
        agent_id, secret = token.split(".")
    except (UnicodeError, ValueError):
        raise AuthenticationFailed() from None
    if (scheme.lower() != "agent" or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", agent_id)
            or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", secret)):
        raise AuthenticationFailed()
    credential = settings.CAPTURE_AGENTS.get(agent_id)
    expected = credential["token_sha256"] if credential else "0" * 64
    matches = hmac.compare_digest(hashlib.sha256(token.encode("ascii")).hexdigest(), expected)
    if not credential or not matches:
        raise AuthenticationFailed()
    return AgentIdentity(agent_id, credential["box"])
