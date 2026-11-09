"""Reintenta únicamente DELETE ya pendientes; nunca vuelve a enviar audio/texto."""
from copy import deepcopy
from datetime import timedelta
import re
import time

from django.utils import timezone
import httpx

from backend.apps.analysis.errors import ProviderError
from backend.apps.analysis.providers.http import request
from backend.apps.analysis.providers.settings import Settings
from .models import FragmentJob


def delete_provider_job(record):
    config = Settings.from_env()
    config.validate("speechmatics")
    region, job_id = record.get("region"), record.get("job_id")
    if region not in {"eu1", "us1", "au1"} or not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", job_id):
        raise ProviderError("PROVIDER_DELETE_ID_INVALID")
    with httpx.Client(headers={"Authorization": f"Bearer {config.speechmatics_key}"},
                      trust_env=False, follow_redirects=False, timeout=3) as client:
        request(client, "DELETE", f"https://{region}.asr.api.speechmatics.com/v2/jobs/{job_id}",
                params={"force": "true"}, attempts=1, deadline=time.monotonic() + 3)


def cleanup_provider_jobs(now, *, delete=delete_provider_job):
    removed = failed = 0
    deadline = time.monotonic() + 10
    for job in FragmentJob.objects.exclude(state=FragmentJob.State.PROCESSING).iterator():
        original = deepcopy(job.checkpoint)
        data = job.checkpoint
        record = data.get("speechmatics", {})
        if not record.get("job_id") or record.get("state") == "deleted":
            continue
        if record.get("state") != "delete_pending" and job.sensitive_expired_at is None:
            continue
        retry = record.get("delete_retry_at")
        if retry and timezone.datetime.fromisoformat(retry) > now:
            continue
        attempts = record.get("delete_attempts", 0) + 1
        try:
            delete(record)
            record.update(state="deleted", delete_error="", delete_retry_at=None)
            removed += 1
        except (ProviderError, OSError, ValueError):
            record.update(state="delete_pending", delete_error="PROVIDER_DELETE_FAILED",
                          delete_retry_at=(now + timedelta(seconds=min(3600, 30 * 2 ** min(attempts, 7)))).isoformat())
            failed += 1
        record["delete_attempts"] = attempts
        # No sobrescribir un checkpoint escrito concurrentemente por el trabajador.
        FragmentJob.objects.filter(pk=job.pk, checkpoint=original).exclude(state=FragmentJob.State.PROCESSING).update(checkpoint=data)
        if removed + failed >= 3 or time.monotonic() >= deadline:
            break
    return removed, failed
