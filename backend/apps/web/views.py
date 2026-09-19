from django.shortcuts import redirect, render


def inicio(request):
    return redirect("web:dashboard")


def dashboard(request):
    return render(request, "web/dashboard.html")


def estadisticas(request):
    return render(request, "web/estadisticas.html")


def alertas(request):
    return redirect("/dashboard#historial-alertas")