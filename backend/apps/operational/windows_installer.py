import asyncio
import os
import re
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.handlers.asgi import ASGIRequest
from django.http import FileResponse, HttpResponse
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.apps.capture.authentication import BoxAgentAuthentication

from .views import IsActiveAdmin


@dataclass(frozen=True)
class PublishedInstaller:
    path: Path
    size: int
    sha256: str

    @property
    def version(self):
        return self.path.parent.name


def _published_release():
    root = Path(settings.PC_WINDOWS_INSTALLER_DIR)
    if not root.is_absolute():
        return None
    try:
        root = root.resolve(strict=True)
        release = (root / "current").resolve(strict=True)
        version = release.name
        if release.parent != root or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
            return None
        public_roots = (settings.BASE_DIR, settings.STATIC_ROOT)
        if any(release.is_relative_to(Path(directory).resolve()) for directory in public_roots):
            return None

        installer = release / f"PsycodeAgent-Setup-{version}-x64.exe"
        checksum = installer.with_suffix(".exe.sha256")
        if any(path.is_symlink() or not path.is_file() for path in (installer, checksum)):
            return None
        with installer.open("rb") as stream:
            size = os.fstat(stream.fileno()).st_size
        if not 0 < size <= 512 * 1024 * 1024:
            return None
        # El operador verifica el hash de los bytes al publicar. Aquí solo se valida el manifiesto.
        with checksum.open("r", encoding="ascii") as stream:
            manifest = stream.read(256)
        match = re.fullmatch(rf"([0-9a-fA-F]{{64}}) [ *]{re.escape(installer.name)}\n?", manifest)
        if match:
            return PublishedInstaller(installer, size, match[1].lower())
    except (OSError, RuntimeError, ValueError):
        return None
    return None


def published_installer():
    """Devuelve el .exe de la versión activa si el par de archivos está disponible."""
    release = _published_release()
    return release.path if release else None


async def _file_chunks(stream, block_size):
    while chunk := await asyncio.to_thread(stream.read, block_size):
        yield chunk


def _download(request, path, content_type="application/octet-stream"):
    try:
        stream = path.open("rb")
    except OSError:
        return None
    response = FileResponse(stream, as_attachment=True, content_type=content_type)
    # El VPS usa ASGI. Un iterador síncrono cargaría el archivo entero en memoria.
    if isinstance(request._request, ASGIRequest):
        response.streaming_content = _file_chunks(stream, 64 * 1024)
    return response


class WindowsInstallerView(APIView):
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def get(self, request, version, checksum=False):
        installer = published_installer()
        if installer and installer.parent.name == version:
            path = installer.with_suffix(".exe.sha256") if checksum else installer
            response = _download(request, path, "text/plain" if checksum else "application/octet-stream")
            if response is not None:
                return response
        return HttpResponse(
            "El instalador solicitado no está disponible. Vuelve a Gestión de PCs y recarga la página.",
            status=404, content_type="text/plain; charset=utf-8",
        )


class AgentWindowsUpdateView(APIView):
    authentication_classes = [BoxAgentAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, version=None):
        if not request.is_secure():
            raise PermissionDenied("Las actualizaciones requieren HTTPS.")
        release = _published_release()
        if release and version is None:
            return Response({"version": release.version, "size": release.size, "sha256": release.sha256})
        if release and version == release.version:
            response = _download(request, release.path)
            if response is not None:
                return response
        return Response(status=404)
