import hashlib
import logging
import os
from contextlib import ExitStack, contextmanager
from pathlib import Path

from django.conf import settings
from django.db import InterfaceError, OperationalError, close_old_connections
from django.http import JsonResponse
from rest_framework.exceptions import AuthenticationFailed

from backend.common.errors import ServiceError, exception_handler

from .authentication import authenticate_agent_header
from .filesystem import lock_file, open_private

logger = logging.getLogger(__name__)


def check_fragment_upload_access(header, source_ip):
    close_old_connections()
    try:
        return authenticate_agent_header(header, source_ip=source_ip)
    except (AuthenticationFailed, ServiceError, OperationalError, InterfaceError) as exc:
        if isinstance(exc, AuthenticationFailed):
            exc.auth_header = "Agent"
        response = exception_handler(exc, {})
        headers = {name: value for name, value in response.items() if name.lower() != "content-type"}
        return JsonResponse(response.data, status=response.status_code, headers=headers)
    finally:
        close_old_connections()


def _try_lock_slot(path, reservations):
    fd = open_private(path, os.O_CREAT | os.O_RDWR)
    try:
        lock_file(fd, blocking=False)
    except BlockingIOError:
        os.close(fd)
        return False
    except BaseException:
        os.close(fd)
        raise
    reservations.callback(os.close, fd)
    return True


@contextmanager
def reserve_fragment_upload(box, *, audio_test=False):
    root = Path(settings.CAPTURE_FRAGMENT_ROOT) / ".upload-slots"
    box_key = hashlib.sha256(box.encode("ascii")).hexdigest()
    prefix = "audio-test-" if audio_test else ""
    with ExitStack() as reservations:
        try:
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            reserved = _try_lock_slot(root / f"{prefix}box-{box_key}.lock", reservations) and any(
                _try_lock_slot(root / f"{prefix}slot-{slot}.lock", reservations)
                for slot in range(settings.CAPTURE_V2_MAX_CONCURRENT_UPLOADS)
            )
        except OSError:
            logger.exception("No se pudo reservar espacio de concurrencia para la carga v2.")
            reserved = False
        yield reserved
