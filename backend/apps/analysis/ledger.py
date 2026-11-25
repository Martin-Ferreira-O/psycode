import json
import os
from pathlib import Path
from .domain import FragmentRejected


class FileFragmentLedger:
    def __init__(self, directory: Path):
        self.directory = directory

    def claim(self, fragment):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.directory / f"{fragment.session_id}.json"
        lock = path.with_suffix(".lock")
        try:
            fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            raise FragmentRejected("Sesión ocupada; revisar reserva si el proceso terminó") from None
        try:
            os.close(fd)
            expected = json.loads(path.read_text())["next"] if path.exists() else 0
            if fragment.sequence != expected:
                raise FragmentRejected("Fragmento duplicado o fuera de secuencia")
            temporary = path.with_suffix(".tmp")
            with temporary.open("w", encoding="utf-8") as stream:
                os.chmod(temporary, 0o600)
                json.dump({"next": expected + 1}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
        finally:
            lock.unlink()
