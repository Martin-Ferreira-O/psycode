import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time

from django.conf import settings
from backend.common.errors import ServiceError

_CACHE = None


def _json_command(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=5, check=True)
    return json.loads(result.stdout)


def _encrypted_ancestry(device):
    if device.get("type") == "crypt":
        return True
    parents = device.get("children", [])
    return bool(parents) and all(_encrypted_ancestry(parent) for parent in parents)


def _linux_encrypted(path):
    mount = _json_command(["findmnt", "--json", "--target", str(path), "--output", "SOURCE,FSTYPE"])["filesystems"][0]
    source = mount["source"].split("[", 1)[0]
    if not source.startswith("/dev/"):
        return False
    devices = _json_command(["lsblk", "--json", "--inverse", "--tree", "--output", "TYPE", source])["blockdevices"]
    return bool(devices) and all(_encrypted_ancestry(device) for device in devices)


def _windows_encrypted(path):
    drive = Path(path).drive
    if not re.fullmatch(r"[A-Za-z]:", drive):
        return False
    script = f"Get-BitLockerVolume -MountPoint '{drive}' | Select-Object ProtectionStatus,EncryptionPercentage | ConvertTo-Json -Compress"
    volume = _json_command(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script])
    return volume["ProtectionStatus"] in (1, "On") and volume["EncryptionPercentage"] == 100


def _existing_parent(path):
    path = Path(path).absolute()
    while not path.exists():
        path = path.parent
    return path


def _key_protected(path, roots):
    path = Path(path).absolute()
    info = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_size < 32:
        return False
    resolved = path.resolve()
    forbidden = [Path(settings.BASE_DIR).resolve(), *[Path(root).resolve() for root in roots]]
    if any(resolved == root or root in resolved.parents for root in forbidden):
        return False
    if os.name == "nt":
        return False
    if info.st_uid not in {0, os.getuid()} or stat.S_IMODE(info.st_mode) & 0o077:
        return False
    return all(not (parent.stat().st_mode & 0o022) for parent in resolved.parents)


def encryption_status():
    roots = [settings.CAPTURE_FRAGMENT_ROOT, Path(settings.DATABASES["default"]["NAME"]).parent,
             settings.ANALYSIS_STATE_ROOT, *settings.SENSITIVE_STORAGE_EXTRA_ROOTS]
    volumes = []
    for index, root in enumerate(roots):
        try:
            path = _existing_parent(root)
            verified = _windows_encrypted(path) if os.name == "nt" else (
                _linux_encrypted(path) if sys.platform.startswith("linux") else False)
        except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError):
            verified = False
        volumes.append({"scope": ["audio", "sql", "analysis"][index] if index < 3 else "extra", "encrypted": verified})
    keys = settings.SENSITIVE_STORAGE_KEY_FILES
    try:
        protected = bool(keys) and all(_key_protected(key, roots) for key in keys)
    except OSError:
        protected = False
    verified = all(item["encrypted"] for item in volumes) and protected
    return {"required": settings.SENSITIVE_STORAGE_ENCRYPTION_REQUIRED, "verified": verified,
            "volumes": volumes, "key_files_protected": protected,
            "code": "ENCRYPTION_VERIFIED" if verified else "ENCRYPTION_UNVERIFIED"}


def require_encrypted_storage():
    global _CACHE
    if not settings.SENSITIVE_STORAGE_ENCRYPTION_REQUIRED:
        return
    signature = (str(settings.CAPTURE_FRAGMENT_ROOT), str(settings.DATABASES["default"]["NAME"]),
                 str(settings.ANALYSIS_STATE_ROOT), tuple(settings.SENSITIVE_STORAGE_EXTRA_ROOTS), tuple(settings.SENSITIVE_STORAGE_KEY_FILES))
    if _CACHE is None or _CACHE[0] != signature or time.monotonic() - _CACHE[1] > 60:
        _CACHE = signature, time.monotonic(), encryption_status()
    if not _CACHE[2]["verified"]:
        raise ServiceError("ENCRYPTION_UNVERIFIED", "El almacenamiento sensible requiere verificar cifrado y protección de claves.", 503)
