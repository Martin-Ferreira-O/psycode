import math
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from backend.common.errors import ServiceError
from backend.common.audit import AuditWriter

from .models import AuthRateLimit


def consume_auth_attempt(scope, identity, *, limit, seconds):
    key = salted_hmac("psycode.auth.rate-limit", f"{scope}:{identity}", algorithm="sha256").hexdigest()
    with transaction.atomic():
        now = timezone.now()
        counter, _ = AuthRateLimit.objects.select_for_update().get_or_create(
            key=key, defaults={"expires_at": now + timedelta(seconds=seconds)},
        )
        if counter.expires_at <= now:
            counter.count = 0
            counter.expires_at = now + timedelta(seconds=seconds)
        limited = counter.count >= limit
        if not limited:
            counter.count += 1
            counter.save(update_fields=["count", "expires_at"])
        retry_after = max(1, math.ceil((counter.expires_at - now).total_seconds()))
    if limited:
        AuditWriter.record("auth.rate_limit", "failure", error_code="AUTH_RATE_LIMITED")
        raise ServiceError(
            "AUTH_RATE_LIMITED", "Demasiados intentos. Intenta más tarde.", 429,
            {"retry_after": retry_after},
        )
