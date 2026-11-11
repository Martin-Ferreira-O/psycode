from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils.decorators import method_decorator
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from backend.apps.operational.views import IsActiveAdmin
from backend.apps.operational.windows_installer import published_installer

from .frontend import render_screen


@ensure_csrf_cookie
def inicio(request):
    return render_screen(request, "login")


def dashboard(request):
    return render_screen(request, "dashboard")


def alertas(request):
    return redirect("/dashboard#historial-alertas")


def evaluaciones(request):
    return render_screen(request, "evaluaciones")


def usuarios(request):
    return render_screen(request, "usuarios")


def bitacora(request):
    return render_screen(request, "bitacora")


def configuracion_operativa(request):
    return render_screen(request, "configuracion_operativa")


def password_reset_confirm(request):
    return render_screen(request, "password_reset_confirm")


def almacenamiento_entrada(request):
    # El JWT HttpOnly tiene Path=/api/v1/: el HTML protegido vive en ese ámbito.
    return redirect("web:almacenamiento")


def pcs_entrada(request):
    return redirect("web:pcs")


@method_decorator(ensure_csrf_cookie, name="dispatch")
class PCPanelView(APIView):
    # La cookie JWT tiene Path=/api/v1/; el HTML también exige autorización real.
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def get(self, request):
        installer = published_installer()
        version = installer.parent.name if installer else None
        return render_screen(
            request,
            "pcs",
            installerVersion=version,
            installerUrl=reverse("operational:pcs_windows_installer", args=[version]) if version else None,
            checksumUrl=reverse("operational:pcs_windows_checksum", args=[version]) if version else None,
        )


@method_decorator(never_cache, name="dispatch")
class StoragePanelView(APIView):
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def get(self, request):
        return render_screen(request, "almacenamiento")
