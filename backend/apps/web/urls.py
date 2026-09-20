from django.urls import path

from . import views

app_name = "web"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("dashboard", views.dashboard, name="dashboard"),
    path("estadisticas", views.estadisticas, name="estadisticas"),
    path("alertas", views.alertas, name="alertas"),
]