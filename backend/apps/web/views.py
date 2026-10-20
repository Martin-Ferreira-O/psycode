from django.shortcuts import redirect, render


def inicio(request):
    return render(request, "web/login.html")


def dashboard(request):
    return render(request, "web/dashboard.html")


def estadisticas(request):
    return render(request, "web/estadisticas.html")


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