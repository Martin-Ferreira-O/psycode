"""Consulta actual de destinatarios; no envía correos ni ejecuta contingencias."""
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from backend.apps.accounts.models import Role
from backend.apps.operational.models import NotificationMode, OperationalConfiguration


@dataclass(frozen=True)
class RecipientResult:
    mode: str | None
    emails: tuple[str, ...]
    reason: str | None = None


class RecipientResolver:
    def resolve(self):
        # No crear configuración ni conservar QuerySets evaluados entre notificaciones.
        config = OperationalConfiguration.objects.filter(pk=1).first()
        if config is None:
            return RecipientResult(None, (), 'SIN_DESTINATARIOS_VALIDOS')
        mode = config.notification_mode
        if mode == NotificationMode.ACTIVE_SUPERVISORS:
            candidates = get_user_model().objects.filter(
                role=Role.SUPERVISOR, is_active=True, is_superuser=False,
            ).order_by('email').values_list('email', flat=True)
        elif mode == NotificationMode.DISTRIBUTION_LIST:
            candidates = [config.primary_email]
        else:
            return RecipientResult(mode, (), 'SIN_DESTINATARIOS_VALIDOS')
        emails = []
        seen = set()
        for candidate in candidates:
            email = candidate.strip()
            try:
                validate_email(email)
            except ValidationError:
                continue
            key = email.casefold()
            if key not in seen:
                seen.add(key)
                emails.append(email)
        return RecipientResult(mode, tuple(emails),
                               None if emails else 'SIN_DESTINATARIOS_VALIDOS')
