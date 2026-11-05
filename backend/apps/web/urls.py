from django.urls import path

from . import views
from backend.apps.capture.storage_views import StoragePanelView

app_name = "web"

urlpatterns = [
    path("api/v1/almacenamiento/panel", StoragePanelView.as_view(), name="almacenamiento"),
    path("configuracion-operativa/almacenamiento", views.almacenamiento_entrada),
    path("", views.inicio, name="inicio"),
    path("dashboard", views.dashboard, name="dashboard"),
    path("estadisticas", views.estadisticas, name="estadisticas"),
    path("alertas", views.alertas, name="alertas"),
    path("evaluaciones", views.evaluaciones, name="evaluaciones"),
    path("usuarios", views.usuarios, name="usuarios"),
    path("bitacora", views.bitacora, name="bitacora"),
    path("configuracion-operativa", views.configuracion_operativa, name="configuracion_operativa"),
    path(
        "password-reset/confirm",
        views.password_reset_confirm,
        name="password_reset_confirm",
    ),
]
