import asyncio
import re
from pathlib import Path

from django.conf import settings
from django.core.handlers.asgi import ASGIRequest
from django.http import FileResponse, HttpResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from .views import IsActiveAdmin


def published_installer():
    """Devuelve el .exe de la versión activa si el par de archivos está disponible."""
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
            if not stream.read(1):
                return None
        # El operador verifica el hash de los bytes al publicar. Aquí solo se valida el manifiesto.
        with checksum.open("r", encoding="ascii") as stream:
            manifest = stream.read(256)
        if re.fullmatch(rf"[0-9a-fA-F]{{64}} [ *]{re.escape(installer.name)}\n?", manifest):
            return installer
    except (OSError, RuntimeError, ValueError):
        return None
    return None


async def _file_chunks(stream, block_size):
    while chunk := await asyncio.to_thread(stream.read, block_size):
        yield chunk


class WindowsInstallerView(APIView):
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def get(self, request, version, checksum=False):
        installer = published_installer()
        if installer and installer.parent.name == version:
            path = installer.with_suffix(".exe.sha256") if checksum else installer
            try:
                stream = path.open("rb")
            except OSError:
                pass
            else:
                response = FileResponse(
                    stream, as_attachment=True,
                    content_type="text/plain" if checksum else "application/octet-stream",
                )
                # El VPS usa ASGI. Un iterador síncrono cargaría el archivo entero en memoria.
                if isinstance(request._request, ASGIRequest):
                    response.streaming_content = _file_chunks(stream, 64 * 1024)
                return response
        return HttpResponse(
            "El instalador solicitado no está disponible. Vuelve a Gestión de PCs y recarga la página.",
            status=404, content_type="text/plain; charset=utf-8",
        )
