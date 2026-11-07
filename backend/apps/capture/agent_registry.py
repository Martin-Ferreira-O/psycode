"""Registro y gestión segura de credenciales de PCs de captura."""

import hashlib
import secrets

from django.utils import timezone

from .models import AgentRegistration


def _generate_credential(agent_id):
    """Genera la credencial completa; solo se devuelve en este momento."""
    secret = secrets.token_urlsafe(32)
    token = f"{agent_id}.{secret}"
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    return token, token_hash


def create_agent(*, name, box):
    """Registra un PC y devuelve su API key una sola vez."""
    agent = AgentRegistration(
        name=name,
        box=box,
        token_sha256="0" * 64,
    )

    # Necesitamos primero el UUID estable para construir la credencial.
    agent.save()

    token, token_hash = _generate_credential(agent.agent_id)
    agent.token_sha256 = token_hash
    agent.save(update_fields=["token_sha256", "updated_at"])

    return agent, token


def renew_credential(agent):
    """Renueva la API key conservando identidad, nombre, box e historial."""
    token, token_hash = _generate_credential(agent.agent_id)

    agent.token_sha256 = token_hash
    agent.revoked_at = None
    agent.save(update_fields=["token_sha256", "revoked_at", "updated_at"])

    return token


def revoke_credential(agent):
    """Revoca la credencial sin eliminar la identidad ni su historial."""
    agent.revoked_at = timezone.now()
    agent.save(update_fields=["revoked_at", "updated_at"])

def revoke_agent(agent):
    """
    Revoca la credencial actual del PC sin eliminar
    su identidad ni su historial.
    """
    if agent.revoked_at is None:
        agent.revoked_at = timezone.now()
        agent.save(
            update_fields=[
                "revoked_at",
                "updated_at",
            ]
        )

    return agent


def renew_agent(agent):
    """
    Genera una nueva credencial manteniendo el mismo agent_id.

    La credencial anterior deja de ser válida inmediatamente.
    Si el PC estaba revocado, queda habilitado nuevamente.
    """
    token, token_hash = _generate_credential(
        agent.agent_id
    )

    agent.token_sha256 = token_hash
    agent.revoked_at = None

    agent.save(
        update_fields=[
            "token_sha256",
            "revoked_at",
            "updated_at",
        ]
    )

    return agent, token