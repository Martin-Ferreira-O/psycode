"""Archivos privados locales, con leases compartidas con la limpieza."""
import hashlib
import os
import re
import struct
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from django.core.files.base import File

from backend.common.errors import ServiceError
from .filesystem import lock_file, open_private, publish_file


class FragmentError(ServiceError):
    def __init__(self, code, status=422):
        super().__init__(code, "Recepción de fragmento rechazada.", status)


@dataclass
class StoredFragment:
    key: str
    size: int
    checksum: str
    keep: bool = False


STORED_KEY = re.compile(r"[0-9a-f]{32}\.blob")


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


class IncomingFragment(File):
    def __init__(self, stream, storage):
        super().__init__(stream, name=stream.name)
        self.storage = storage

    def close(self):
        if self.closed:
            return
        with self.storage.allocation_lock():
            self.file.close()
            Path(self.name).unlink(missing_ok=True)


class FragmentStorage:
    def __init__(self, root, max_bytes):
        self.root = Path(root)
        self.max_bytes = max_bytes

    def path(self, key):
        if not isinstance(key, str) or not STORED_KEY.fullmatch(key):
            raise FragmentError("INVALID_STORAGE_KEY", 500)
        path = self.root / key
        if not path.is_file():
            raise FragmentError("FRAGMENT_NOT_FOUND", 500)
        return path

    @contextmanager
    def lease(self, key):
        path = self.path(key)
        lock_path = self.root / f".{key}.lock"
        fd = open_private(lock_path, os.O_CREAT | os.O_RDWR)
        try:
            lock_file(fd, blocking=False)
            yield path
        finally:
            os.close(fd)

    def delete(self, key):
        path = self.path(key)
        lock_path = self.root / f".{key}.lock"
        with self.allocation_lock():
            fd = open_private(lock_path, os.O_CREAT | os.O_RDWR)
            try:
                lock_file(fd, blocking=False)
                path.unlink(missing_ok=True)
            finally: os.close(fd)
            
            try:lock_path.unlink(missing_ok=True)
            
            except OSError:
                pass
                

    @contextmanager
    def allocation_lock(self, *, cleanup=False):
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt":
            self.root.chmod(0o700)
        fd = open_private(self.root / ".allocation.lock", os.O_CREAT | os.O_RDWR)
        try:
            lock_file(fd, exclusive=cleanup, blocking=not cleanup)
            yield
        finally:
            os.close(fd)

    def incoming(self):
        """El parser cierra y elimina este archivo, incluso si interrumpe la carga."""
        from .encryption import require_encrypted_storage
        require_encrypted_storage()
        with self.allocation_lock():
            stream = tempfile.NamedTemporaryFile(
                dir=self.root,
                prefix="incoming-",
                suffix=".part",
                delete=False,
            )
            try:
                lock_file(stream)
            except BaseException:
                stream.close()
                Path(stream.name).unlink(missing_ok=True)
                raise
            return IncomingFragment(stream, self)

    @contextmanager
    def stage(self, upload, checksum):
        from .encryption import require_encrypted_storage
        require_encrypted_storage()
        key = uuid4().hex + ".blob"
        path = self.root / ("incoming-" + uuid4().hex + ".part")
        with self.allocation_lock():
            fd = open_private(path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            stream = os.fdopen(fd, "w+b")
            try:
                lock_file(stream)
            except BaseException:
                stream.close()
                path.unlink(missing_ok=True)
                raise
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
            os.fsync(stream.fileno())
            with self.allocation_lock():
                stream.close()
                destination = self.root / key
                try:
                    publish_file(path, destination)
                finally:
                    if not path.exists():
                        path = destination
                stream = os.fdopen(open_private(path, os.O_RDWR), "r+b")
                lock_file(stream)
            yield stored
        finally:
            if stored.keep:
                stream.close()
            else:
                with self.allocation_lock():
                    stream.close()
                    path.unlink(missing_ok=True)
