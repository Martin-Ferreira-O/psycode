import os
import re
import stat
from dataclasses import dataclass

from django.utils import timezone

from .models import FragmentJob
from .filesystem import lock_file, open_private

MANAGED_FILE = re.compile(r"(?:[0-9a-f]{32}\.blob|incoming-[A-Za-z0-9_-]+\.part)")


@dataclass
class CleanupResult:
    removed: int = 0
    protected: int = 0
    busy: int = 0


def clean_orphan_fragments(storage, *, older_than_seconds, now=None):
    if older_than_seconds <= 0:
        raise ValueError("La antigüedad debe ser positiva.")
    cutoff = (now or timezone.now()).timestamp() - older_than_seconds
    result = CleanupResult()
    try:
        with storage.allocation_lock(cleanup=True):
            with os.scandir(storage.root) as entries:
                for entry in entries:
                    if not MANAGED_FILE.fullmatch(entry.name) or not entry.is_file(follow_symlinks=False):
                        continue
                    try:
                        fd = open_private(entry.path, os.O_RDWR)
                        try:
                            lock_file(fd, blocking=False)
                            info = os.fstat(fd)
                            if not stat.S_ISREG(info.st_mode) or info.st_mtime > cutoff:
                                continue
                            if FragmentJob.objects.filter(storage_key=entry.name).exists():
                                result.protected += 1
                                continue
                        finally:
                            os.close(fd)
                        os.unlink(entry.path)
                        result.removed += 1
                    except FileNotFoundError:
                        continue
                    except BlockingIOError:
                        result.busy += 1
    except BlockingIOError:
        result.busy += 1
    return result
