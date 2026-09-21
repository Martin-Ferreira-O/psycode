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