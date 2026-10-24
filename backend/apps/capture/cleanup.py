"""Recuperar archivos huérfanos sin tocar cargas vivas ni archivos de trabajos."""
import fcntl
import os
import re
import stat
from dataclasses import dataclass

from django.utils import timezone

from .models import FragmentJob

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
        # Impide la carrera entre crear el archivo y tomar su lease. Otra
        # limpieza sale sin esperar; los uploads ya iniciados conservan su lock.
        with storage.allocation_lock(cleanup=True):
            with os.scandir(storage.root) as entries:
                for entry in entries:
                    if not MANAGED_FILE.fullmatch(entry.name) or not entry.is_file(follow_symlinks=False):
                        continue
                    try:
                        fd = os.open(entry.path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
                        try:
                            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            info = os.fstat(fd)
                            if not stat.S_ISREG(info.st_mode) or info.st_mtime > cutoff:
                                continue
                            # Consultar incluso para temporales: ante indisponibilidad
                            # SQL, fallar cerrado y nunca inferir que no hay trabajos.
                            if FragmentJob.objects.filter(storage_key=entry.name).exists():
                                result.protected += 1
                                continue
                            os.unlink(entry.path)
                            result.removed += 1
                        finally:
                            os.close(fd)
                    except FileNotFoundError:
                        continue  # El parser pudo cerrar y eliminar su temporal.
                    except BlockingIOError:
                        result.busy += 1
    except BlockingIOError:
        result.busy += 1
    return result
