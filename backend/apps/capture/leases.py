from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from .models import RuntimeLease


def acquire(name, owner, *, ttl=30, replace=False):
    now = timezone.now()
    with transaction.atomic():
        row, created = RuntimeLease.objects.select_for_update().get_or_create(
            name=name, defaults={"owner": owner, "expires_at": now + timedelta(seconds=ttl)})
        if not created and not replace and row.owner != owner and row.expires_at > now:
            return False
        row.owner, row.expires_at = owner, now + timedelta(seconds=ttl)
        row.save(update_fields=["owner", "expires_at"])
        return True


def owned(name, owner):
    return RuntimeLease.objects.filter(name=name, owner=owner, expires_at__gt=timezone.now()).exists()


def release(name, owner):
    RuntimeLease.objects.filter(name=name, owner=owner).delete()
