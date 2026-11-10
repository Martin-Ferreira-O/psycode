#!/usr/bin/python3 -I
"""Activa pares inmutables de GitHub Releases y permite revertirlos localmente."""

import argparse
import fcntl
import hashlib
import os
from pathlib import Path
import re
import signal
import sys
from tempfile import TemporaryDirectory


ROOT = Path("/srv/psycode/shared/agent-installers")
VERSION = r"(?:0|[1-9][0-9]{0,4})(?:\.(?:0|[1-9][0-9]{0,4})){2}"
MAX_SIZE = 512 * 1024 * 1024
HOLD = ".publication-paused"


def version_key(version):
    if not re.fullmatch(VERSION, version):
        raise ValueError("Se esperaba una versión estable X.Y.Z.")
    return tuple(map(int, version.split(".")))


def names(version):
    executable = f"PsycodeAgent-Setup-{version}-x64.exe"
    return executable, executable + ".sha256"


def manifest_digest(manifest, executable):
    match = re.fullmatch(rb"([0-9a-fA-F]{64}) [ *]" + re.escape(executable.encode("ascii")) + rb"\r?\n", manifest)
    if not match:
        raise ValueError("El manifiesto SHA-256 no corresponde al nombre y versión del instalador.")
    return match[1].decode("ascii").lower()


def activate(root, version):
    with TemporaryDirectory(dir=root, prefix=".link-") as temp:
        link = Path(temp) / "current"
        link.symlink_to(version)
        link.replace(root / "current")


def verify_saved(directory, version):
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("El directorio de la versión no existe o no es válido.")
    executable, checksum = (directory / name for name in names(version))
    if any(path.is_symlink() or not path.is_file() for path in (executable, checksum)):
        raise ValueError("La versión guardada no contiene un par de archivos válido.")
    with checksum.open("rb") as stream:
        expected = manifest_digest(stream.read(256), executable.name)
    with executable.open("rb") as stream:
        if not 0 < os.fstat(stream.fileno()).st_size <= MAX_SIZE:
            raise ValueError("Tamaño del instalador fuera de rango.")
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
        if digest.hexdigest() != expected:
            raise ValueError("SHA-256 incorrecto en la versión guardada.")
    return expected


def receive(root, source):
    if (root / HOLD).exists():
        raise ValueError("Publicación pausada por mantenimiento. Reintenta después de reanudar.")

    version_line = source.readline(20).decode("ascii")
    if not version_line.endswith("\n"):
        raise ValueError("Falta la versión del envío.")
    version = version_line[:-1]
    candidate = version_key(version)
    executable, checksum = names(version)
    size_line = source.readline(12)
    if not re.fullmatch(rb"[1-9][0-9]{0,8}\n", size_line) or not 0 < int(size_line) <= MAX_SIZE:
        raise ValueError("Tamaño del instalador fuera de rango.")
    manifest = source.readline(256)
    expected = manifest_digest(manifest, executable)

    versions = [version_key(path.name) for path in root.iterdir()
                if re.fullmatch(VERSION, path.name) and path.is_dir() and not path.is_symlink()]
    current = root / "current"
    active = os.readlink(current) if current.is_symlink() else ""
    if active:
        versions.append(version_key(active))
    if versions and candidate < max(versions):
        print(f"{version} omitida. Ya se recibió una versión superior.")
        return

    with TemporaryDirectory(dir=root, prefix=".incoming-") as temp:
        staged = Path(temp) / version
        staged.mkdir()
        remaining = int(size_line)
        with (staged / executable).open("wb") as stream:
            while remaining:
                block = source.read(min(remaining, 1024 * 1024))
                if not block:
                    raise ValueError("Transferencia incompleta.")
                stream.write(block)
                remaining -= len(block)
            stream.flush()
            os.fsync(stream.fileno())
        if source.read(1):
            raise ValueError("Datos adicionales después del instalador.")
        with (staged / checksum).open("wb") as stream:
            stream.write(manifest)
            stream.flush()
            os.fsync(stream.fileno())
        verify_saved(staged, version)

        target = root / version
        if target.exists() or target.is_symlink():
            if verify_saved(target, version) != expected:
                raise ValueError("Esta versión ya existe con otros bytes.")
        else:
            for path, mode in ((staged, 0o750), (staged / executable, 0o640), (staged / checksum, 0o640)):
                os.chown(path, -1, root.stat().st_gid)
                path.chmod(mode)
            staged.rename(target)
        if active != version:
            activate(root, version)
        print(f"Versión activa: {version} (SHA-256 {expected}).")


def operate(root, action, version=None, source=None):
    with (root / ".publication.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if action == "receive":
            receive(root, source)
        elif action == "rollback":
            version_key(version)
            verify_saved(root / version, version)
            (root / HOLD).touch(mode=0o600)
            activate(root, version)
            print(f"Versión activa: {version}. Publicación automática pausada.")
        elif action == "resume":
            (root / HOLD).unlink(missing_ok=True)
            print("Publicación automática reanudada.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("receive")
    commands.add_parser("resume")
    commands.add_parser("rollback").add_argument("version")
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, interrupt)
    try:
        os.umask(0o077)
        operate(ROOT, args.action, getattr(args, "version", None), sys.stdin.buffer)
    except (OSError, ValueError) as error:
        print(f"Publicación rechazada: {error}", file=sys.stderr)
        return 1
    return 0


def interrupt(_signal, _frame):
    raise SystemExit("Publicación interrumpida.")


if __name__ == "__main__":
    sys.exit(main())
