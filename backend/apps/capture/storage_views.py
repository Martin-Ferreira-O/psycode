"""Administración de almacenamiento, sin edición web de la política."""
from django.core import signing
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.utils.decorators import method_decorator
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from backend.apps.operational.views import IsActiveAdmin
from backend.common.errors import ServiceError
from backend.common.responses import success_response
from backend.config.composition import fragment_storage
from .encryption import encryption_status
from .retention import cleanup, inventory, serialize_run
from .storage_audit import flush_storage_audit

SALT = "psycode.storage.preview.v1"


@method_decorator(never_cache, name="dispatch")
class StoragePanelView(APIView):
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def get(self, request):
        return render(request, "web/almacenamiento.html")


@method_decorator(never_cache, name="dispatch")
class StorageStatusView(APIView):
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def get(self, request):
        data = inventory(fragment_storage())
        data.pop("candidates")
        data["encryption"] = encryption_status()
        return success_response(data, "Almacenamiento del servidor")


@method_decorator(never_cache, name="dispatch")
class StoragePreviewView(APIView):
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def post(self, request):
        data = inventory(fragment_storage())
        files = data.pop("candidates")
        data["preview_bytes"] = sum(info[2] for _, info in files)
        data["preview_files"] = len(files)
        data["preview_token"] = signing.dumps({"actor": str(request.user.pk), "files": files}, salt=SALT, compress=True)
        data["expires_in_seconds"] = 300
        return success_response(data, "Vista previa; las protecciones se vuelven a comprobar al confirmar")


@method_decorator(never_cache, name="dispatch")
class StorageCleanupView(APIView):
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def post(self, request):
        token = request.data.get("preview_token")
        if not isinstance(token, str) or len(token) > 200000:
            raise ServiceError("STORAGE_PREVIEW_REQUIRED", "Solicita una vista previa antes de liberar espacio.")
        try:
            preview = signing.loads(token, salt=SALT, max_age=300)
            if preview["actor"] != str(request.user.pk):
                raise signing.BadSignature()
        except (signing.BadSignature, KeyError, TypeError):
            raise ServiceError("STORAGE_PREVIEW_EXPIRED", "La vista previa venció o es inválida. Actualízala.", 409) from None
        try:
            run = cleanup(fragment_storage(), source="manual", actor_id=request.user.pk, candidates=preview["files"])
        except BlockingIOError:
            raise ServiceError("STORAGE_CLEANUP_BUSY", "Hay otra limpieza en ejecución. Actualiza el estado.", 409) from None
        except OSError:
            raise ServiceError("STORAGE_UNAVAILABLE", "No se pudo completar la limpieza. Revisa el estado e inténtalo nuevamente.", 503) from None
        flush_storage_audit()
        return success_response(serialize_run(run), "Limpieza finalizada")
