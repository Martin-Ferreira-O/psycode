import os
import shutil
import stat
from contextlib import contextmanager
from datetime import timedelta

from django.conf import settings
from django.db import DatabaseError, transaction
from django.utils import timezone

from backend.apps.analysis.domain import EVIDENCE_ABSTENTION_CODES

from .cleanup import MANAGED_FILE
from .filesystem import lock_file, open_private
from .provider_cleanup import cleanup_provider_jobs
from .models import AUDIO_TEST_ORIGIN, CaptureSession, FragmentJob, StorageCleanupRun, StorageDeletion

AUDIO_MIN_AGE = timedelta(hours=24)
RECOVERY_WINDOW = timedelta(days=7)
INTERVAL = timedelta(minutes=15)
MAX_FILES = 1000


def reception_closed(session, now):
    if session.actual_end is None:
        return False
    if session.final_sequence is not None and session.next_sequence == session.final_sequence + 1:
        return True
    deadline = session.reception_extended_until or (session.actual_end + timedelta(seconds=settings.CAPTURE_RECEPTION_GRACE_SECONDS))
    return now >= deadline


def expired_session(session, now):
    if not reception_closed(session, now):
        return False
    jobs = FragmentJob.objects.filter(sequence__session=session)
    return (not jobs.filter(state=FragmentJob.State.PROCESSING).exists()
            and not jobs.filter(sequence__accepted_at__gt=now - RECOVERY_WINDOW).exists())


def protection(job, info, now):
    if job is None:
        return "temporal_reciente" if info.st_mtime > now.timestamp() - settings.CAPTURE_ORPHAN_MAX_AGE_SECONDS else None
    if now < job.sequence.accepted_at + AUDIO_MIN_AGE:
        return "minimo_24_horas"
    if job.state == FragmentJob.State.PROCESSING:
        return "analisis_activo"
    if job.state != FragmentJob.State.COMPLETED and job.sensitive_expired_at is None:
        return "recuperable"
    return None


@contextmanager
def file_guard(storage, key, *, close_file=False):
    with storage.allocation_lock(cleanup=True):
        lease = open_private(storage.root / f".{key}.lock", os.O_CREAT | os.O_RDWR)
        try:
            lock_file(lease, blocking=False)
            fd = open_private(storage.root / key, os.O_RDWR)
            try:
                lock_file(fd, blocking=False)
                info = os.fstat(fd)
                if close_file:
                    os.close(fd)
                    fd = None
                yield info
            finally:
                if fd is not None:
                    os.close(fd)
        finally:
            os.close(lease)


def entries(storage):
    if storage.root.is_symlink():
        raise OSError("STORAGE_ROOT_INVALID")
    if not storage.root.exists():
        return []
    with os.scandir(storage.root) as scan:
        return sorted(entry.name for entry in scan
                      if MANAGED_FILE.fullmatch(entry.name) and entry.is_file(follow_symlinks=False))


def fingerprint(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]


def inventory(storage, *, now=None):
    now = now or timezone.now()
    jobs = {j.storage_key: j for j in FragmentJob.objects.select_related("sequence__session")}
    totals = {"managed_bytes": 0, "reclaimable_bytes": 0, "protected_bytes": 0,
              "protected_files": 0, "reclaimable_files": 0, "reasons": {}, "candidates": []}
    for key in entries(storage):
        try:
            info = (storage.root / key).stat(follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                continue
            totals["managed_bytes"] += info.st_size
            reason = protection(jobs.get(key), info, now)
            if reason is None:
                try:
                    with file_guard(storage, key):
                        pass
                except (BlockingIOError, PermissionError):
                    reason = "archivo_en_uso"
            if reason:
                totals["protected_bytes"] += info.st_size
                totals["protected_files"] += 1
                totals["reasons"][reason] = totals["reasons"].get(reason, 0) + 1
            else:
                totals["reclaimable_bytes"] += info.st_size
                totals["reclaimable_files"] += 1
                if len(totals["candidates"]) < MAX_FILES:
                    totals["candidates"].append([key, fingerprint(info)])
        except FileNotFoundError:
            continue
    parent = storage.root
    while not parent.exists():
        parent = parent.parent
    disk = shutil.disk_usage(parent)
    totals.update(total_bytes=disk.total, used_bytes=disk.used, available_bytes=disk.free,
                  pending_deletions=StorageDeletion.objects.exclude(state="deleted").count(),
                  intervention_deletions=StorageDeletion.objects.filter(attempts__gte=10).exclude(state="deleted").count(),
                  stale_active_jobs=FragmentJob.objects.filter(state=FragmentJob.State.PROCESSING, processing_started_at__lt=now - timedelta(hours=1)).count(),
                  review_jobs=FragmentJob.objects.filter(state=FragmentJob.State.REVIEW, sensitive_expired_at__isnull=True).count(),
                  expired_jobs=FragmentJob.objects.filter(sensitive_expired_at__isnull=False).count())
    last = StorageCleanupRun.objects.order_by("-started_at").first()
    totals["last_run"] = serialize_run(last) if last else None
    due = (last.started_at + INTERVAL) if last else now
    totals.update(next_run_at=due.isoformat(), delay_seconds=max(0, int((now - due).total_seconds())),
                  interval_seconds=int(INTERVAL.total_seconds()), retention_hours=24, recovery_days=7,
                  audit_pending=StorageCleanupRun.objects.filter(finished_at__isnull=False, audit_sent_at__isnull=True).count())
    return totals


def serialize_run(run):
    return {name: (getattr(run, name).isoformat() if getattr(run, name) is not None else None)
            for name in ("started_at", "finished_at")} | {
        name: getattr(run, name) for name in ("outcome", "source", "freed_bytes", "removed", "failures", "protected", "checkpoints", "provider_deleted", "provider_failures", "error_code")}


@transaction.atomic
def purge_checkpoints(now):
    cleared = 0
    for session in CaptureSession.objects.select_for_update().filter(actual_end__isnull=False):
        if not reception_closed(session, now):
            continue
        jobs = list(FragmentJob.objects.select_for_update().filter(sequence__session=session))
        if any(job.state == FragmentJob.State.PROCESSING for job in jobs):
            continue
        expired = expired_session(session, now)
        if expired:
            for job in jobs:
                if job.state != FragmentJob.State.COMPLETED and job.sensitive_expired_at is None:
                    job.state = FragmentJob.State.REVIEW
                    job.last_error_code = "RETENTION_EXPIRED"
                    job.sensitive_expired_at = now
                    job.retry_at = None
                    job.save(update_fields=["state", "last_error_code", "sensitive_expired_at", "retry_at"])
        if not expired and any(job.state != FragmentJob.State.COMPLETED for job in jobs):
            continue
        for job in jobs:
            speech = job.checkpoint.get("speechmatics", {})
            keep = {"speechmatics": speech} if speech.get("state") not in (None, "deleted") else {}
            if (session.origin == AUDIO_TEST_ORIGIN and job.state == FragmentJob.State.COMPLETED
                    and job.result == FragmentJob.Result.RISK_DETECTED and job.checkpoint.get("test_alerts")):
                keep["test_alerts"] = job.checkpoint["test_alerts"]
            if (session.origin == AUDIO_TEST_ORIGIN and job.state == FragmentJob.State.COMPLETED
                    and job.result == FragmentJob.Result.INDETERMINATE):
                codes = job.checkpoint.get("test_error_codes",
                                           job.checkpoint.get("block_result", {}).get("error_codes", ()))
                if codes:
                    keep["test_error_codes"] = codes
            if session.origin != AUDIO_TEST_ORIGIN and job.state == FragmentJob.State.COMPLETED:
                if job.checkpoint.get("analysis_review"):
                    keep["analysis_review"] = job.checkpoint["analysis_review"]
                block = job.checkpoint.get("block_result", {})
                codes = set(job.checkpoint.get("analysis_error_codes", block.get("error_codes", ())))
                for decision in block.get("decisions", ()):
                    for turns in decision.get("review_verdicts", {}).values():
                        codes.update(EVIDENCE_ABSTENTION_CODES[v] for v in turns.values()
                                     if v in EVIDENCE_ABSTENTION_CODES)
                allowed = {*EVIDENCE_ABSTENTION_CODES.values(), "CONTEXT_NOT_EVALUABLE", "TEXT_NOT_EVALUABLE",
                           "JEV_BELOW_THRESHOLD"}
                reasons = sorted(allowed.intersection(codes))
                if reasons:
                    keep["analysis_error_codes"] = reasons
            if job.checkpoint != keep:
                job.checkpoint = keep
                job.save(update_fields=["checkpoint"])
                cleared += 1
    return cleared


def _remove(storage, key, expected, run, now):
    if not MANAGED_FILE.fullmatch(key):
        return
    try:
        with file_guard(storage, key, close_file=True) as info:
            if expected is not None and fingerprint(info) != expected:
                run.protected += 1
                return
            with transaction.atomic():
                job = FragmentJob.objects.select_for_update().select_related("sequence__session").filter(storage_key=key).first()
                if protection(job, info, now):
                    run.protected += 1
                    return
                debt, _ = StorageDeletion.objects.get_or_create(key=key, defaults={"size": info.st_size})
                if debt.state == "deleted":
                    return
                if debt.retry_at and debt.retry_at > now:
                    run.protected += 1
                    return
                debt.attempts += 1
                debt.save(update_fields=["attempts"])
            os.unlink(storage.root / key)
            _sync_directory(storage.root)
            run.freed_bytes += info.st_size
            run.removed += 1
            StorageDeletion.objects.filter(pk=debt.pk).update(state="deleted", retry_at=None, error_code="", removed_at=now)
    except FileNotFoundError:
        StorageDeletion.objects.filter(key=key).update(state="deleted", retry_at=None, error_code="", removed_at=now)
    except BlockingIOError:
        run.protected += 1
    except OSError:
        run.failures += 1
        debt, _ = StorageDeletion.objects.get_or_create(key=key)
        debt.attempts = max(1, debt.attempts)
        debt.state = "failed"
        debt.error_code = "STORAGE_DELETE_FAILED"
        debt.retry_at = now + timedelta(seconds=min(3600, 30 * 2 ** min(debt.attempts, 7)))
        debt.save(update_fields=["state", "error_code", "retry_at", "attempts"])


def _sync_directory(root):
    if os.name != "nt":
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def cleanup(storage, *, now=None, source="automatic", actor_id=None, candidates=None):
    now = now or timezone.now()
    storage.root.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = open_private(storage.root / ".retention.lock", os.O_CREAT | os.O_RDWR)
    try:
        lock_file(fd, blocking=False)
        StorageCleanupRun.objects.filter(outcome="running").update(outcome="interrupted", finished_at=now, error_code="CLEANUP_INTERRUPTED")
        run = StorageCleanupRun.objects.create(started_at=now, source=source, actor_id=actor_id)
        try:
            run.checkpoints = purge_checkpoints(now)
            run.provider_deleted, run.provider_failures = cleanup_provider_jobs(now)
            run.failures += run.provider_failures
            files = candidates if candidates is not None else [[key, None] for key in entries(storage)]
            for key, expected in files:
                _remove(storage, key, expected, run, now)
                if run.removed + run.failures >= MAX_FILES:
                    break
            for debt in StorageDeletion.objects.exclude(state="deleted"):
                if not (storage.root / debt.key).exists():
                    _sync_directory(storage.root)
                    debt.state, debt.removed_at, debt.retry_at = "deleted", now, None
                    debt.error_code = ""
                    debt.save(update_fields=["state", "removed_at", "retry_at", "error_code"])
            run.outcome = "partial" if run.failures else "success"
        except (DatabaseError, OSError):
            run.outcome, run.error_code = "failure", "STORAGE_CLEANUP_FAILED"
            run.failures += 1
            raise
        finally:
            run.finished_at = timezone.now()
            run.save()
        return run
    finally:
        os.close(fd)
