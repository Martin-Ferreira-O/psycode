"""Archivos privados locales, con leases POSIX compartidas con la limpieza."""
import fcntl
import hashlib
import os
import struct
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from backend.common.errors import ServiceError


class FragmentError(ServiceError):
    def __init__(self, code, status=422):
        super().__init__(code, "Recepción de fragmento rechazada.", status)


@dataclass
class StoredFragment:
    key: str
    size: int
    checksum: str
    keep: bool = False


def validate_wav(stream, size):
    """RIFF completo: PCM lineal, mono, 16 kHz, 16 bits; sin decodificar audio."""
    stream.seek(0)
    header = stream.read(12)
    if len(header) != 12:
        raise FragmentError("INVALID_FRAGMENT_FILE")
    magic, length, kind = struct.unpack("<4sI4s", header)
    if magic != b"RIFF" or kind != b"WAVE" or length + 8 != size:
        raise FragmentError("INVALID_FRAGMENT_FILE")
    position, has_format, has_data = 12, False, False
    while position < size:
        chunk = stream.read(8)
        if len(chunk) != 8:
            raise FragmentError("INVALID_FRAGMENT_FILE")
        tag, length = struct.unpack("<4sI", chunk)
        end = position + 8 + length + (length % 2)
        if end > size:
            raise FragmentError("INVALID_FRAGMENT_FILE")
        if tag == b"fmt ":
            if has_format or has_data or length < 16:
                raise FragmentError("INVALID_FRAGMENT_FILE")
            values = struct.unpack("<HHIIHH", stream.read(16))
            if values != (1, 1, 16000, 32000, 2, 16):
                raise FragmentError("FRAGMENT_FORMAT_UNSUPPORTED", 415)
            has_format = True
        elif tag == b"data":
            if not has_format or has_data or not length or length % 2:
                raise FragmentError("INVALID_FRAGMENT_FILE")
            has_data = True
        stream.seek(end)
        position = end
    if not has_format or not has_data:
        raise FragmentError("INVALID_FRAGMENT_FILE")


class FragmentStorage:
    def __init__(self, root, max_bytes):
        self.root = Path(root)
        self.max_bytes = max_bytes

    @contextmanager
    def allocation_lock(self, *, cleanup=False):
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.chmod(0o700)
        fd = os.open(self.root / ".allocation.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            operation = (fcntl.LOCK_EX | fcntl.LOCK_NB) if cleanup else fcntl.LOCK_SH
            fcntl.flock(fd, operation)
            yield
        finally:
            os.close(fd)

    def incoming(self):
        """El parser cierra y elimina este archivo, incluso si interrumpe la carga."""
        with self.allocation_lock():
            stream = tempfile.NamedTemporaryFile(dir=self.root, prefix="incoming-", suffix=".part")
            try:
                fcntl.flock(stream, fcntl.LOCK_EX)
            except BaseException:
                stream.close()
                raise
            return stream

    @contextmanager
    def stage(self, upload, checksum):
        key = uuid4().hex + ".blob"
        path = self.root / key
        with self.allocation_lock():
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            stream = os.fdopen(fd, "w+b")
            fcntl.flock(stream, fcntl.LOCK_EX)
        stored = StoredFragment(key, 0, "")
        try:
            digest = hashlib.sha256()
            for chunk in upload.chunks(chunk_size=64 * 1024):
                stored.size += len(chunk)
                if stored.size > self.max_bytes:
                    raise FragmentError("FRAGMENT_TOO_LARGE", 413)
                digest.update(chunk)
                stream.write(chunk)
            if not stored.size:
                raise FragmentError("EMPTY_FRAGMENT", 422)
            stored.checksum = digest.hexdigest()
            if stored.checksum != checksum:
                raise FragmentError("CHECKSUM_MISMATCH")
            stream.flush()
            validate_wav(stream, stored.size)
            # Archivo Y entrada de directorio deben ser durables antes del commit SQL.
            os.fsync(stream.fileno())
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            yield stored
        finally:
            try:
                if not stored.keep:
                    path.unlink(missing_ok=True)
            finally:
                stream.close()
