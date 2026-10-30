from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from backend.apps.accounts.models import Role
from backend.apps.operational.models import NotificationMode, OperationalConfiguration


def _valid_email(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    email = value.strip()
    if not email:
        return None
    try:
        validate_email(email)
    except ValidationError:
        return None
    return email


@dataclass(frozen=True)
class RecipientResult:
    mode: str | None
    emails: tuple[str, ...]
    reason: str | None = None
    backup_enabled: bool = False
    backup_email: str | None = None


class RecipientResolver:
    def resolve(self) -> RecipientResult:
        config = OperationalConfiguration.objects.filter(pk=1).first()
        if config is None:
            return RecipientResult(None, (), 'SIN_DESTINATARIOS_VALIDOS', False, None)

        backup_enabled = bool(getattr(config, 'backup_enabled', False))
        backup_email = _valid_email(getattr(config, 'backup_email', '')) if backup_enabled else None

        mode = config.notification_mode
        if mode == NotificationMode.ACTIVE_SUPERVISORS:
            candidates = get_user_model().objects.filter(
                role=Role.SUPERVISOR, is_active=True, is_superuser=False,
            ).order_by('email').values_list('email', flat=True)
        elif mode == NotificationMode.DISTRIBUTION_LIST:
            candidates = [config.primary_email]
        else:
            return RecipientResult(mode, (), 'SIN_DESTINATARIOS_VALIDOS', backup_enabled, backup_email)

        emails = []
        seen = set()
        for candidate in candidates:
            email = _valid_email(candidate)
            if email is None:
                continue
            key = email.casefold()
            if key not in seen:
                seen.add(key)
                emails.append(email)

        return RecipientResult(
            mode,
            tuple(emails),
            None if emails else 'SIN_DESTINATARIOS_VALIDOS',
            backup_enabled,
            backup_email,
        )
