from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils.decorators import method_decorator
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from backend.apps.operational.views import IsActiveAdmin
from backend.apps.operational.windows_installer import published_installer


@ensure_csrf_cookie
def inicio(request):
    return render(request, "web/login.html")


def dashboard(request):
    return render(request, "web/dashboard.html")


def alertas(request):
    return redirect("/dashboard#historial-alertas")


def evaluaciones(request):
    return render(request, "web/evaluaciones.html")


def usuarios(request):
    return render(request, "web/usuarios.html")


def bitacora(request):
    return render(request, "web/bitacora.html")


def configuracion_operativa(request):
    return render(request, "web/configuracion_operativa.html")


def password_reset_confirm(request):
    return render(request, "web/password_reset_confirm.html")


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
        return render(request, "web/pcs.html", {
            "installer_version": installer.parent.name if installer else None,
        })
