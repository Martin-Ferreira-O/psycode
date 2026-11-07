from django.urls import path
from .views import (
    OperationalConfigView,
    AgentRegistrationListCreateView,
    AgentRegistrationRevokeView,
    AgentRegistrationRenewView,
    AgentConnectivityHistoryView,
)
from backend.apps.capture.storage_views import StorageStatusView, StoragePreviewView, StorageCleanupView

app_name = "operational"

urlpatterns = [
    path("almacenamiento", StorageStatusView.as_view(), name="storage_status"),
    path("almacenamiento/vista-previa", StoragePreviewView.as_view(), name="storage_preview"),
    path("almacenamiento/liberar", StorageCleanupView.as_view(), name="storage_cleanup"),
    path("configuracion-operativa", OperationalConfigView.as_view(), name="configuracion_operativa"),
    path("pcs", AgentRegistrationListCreateView.as_view(), name="pcs"),
    path("pcs/<uuid:agent_id>/revocar",AgentRegistrationRevokeView.as_view(),name="pcs_revoke",),
    path("pcs/<uuid:agent_id>/renovar",AgentRegistrationRenewView.as_view(),name="pcs_renew",),
    path("pcs/<uuid:agent_id>/historial",AgentConnectivityHistoryView.as_view(),name="pcs_connectivity_history",),
    ]

