from django.urls import path
from .views import OperationalConfigView
from backend.apps.capture.storage_views import StorageStatusView, StoragePreviewView, StorageCleanupView

app_name = "operational"

urlpatterns = [
    path("almacenamiento", StorageStatusView.as_view(), name="storage_status"),
    path("almacenamiento/vista-previa", StoragePreviewView.as_view(), name="storage_preview"),
    path("almacenamiento/liberar", StorageCleanupView.as_view(), name="storage_cleanup"),
    path("configuracion-operativa", OperationalConfigView.as_view(), name="configuracion_operativa"),
]