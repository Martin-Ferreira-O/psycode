from django.urls import path
from backend.apps.capture.pairing import PCEnrollmentView, PCReEnrollmentView, PCPairingExchangeView, PCPairingConfirmView, PCEnrollmentCancelView
from .views import (
    OperationalConfigView,
    AgentRegistrationListCreateView,
    AgentRegistrationRevokeView,
    AgentRegistrationRenewView,
    AgentConnectivityHistoryView,
    SmileRoomListView,
)
from backend.apps.capture.storage_views import StorageStatusView, StoragePreviewView, StorageCleanupView

app_name = "operational"

urlpatterns = [
    path("pcs/salas", SmileRoomListView.as_view(), name="pc_rooms"),
    path("pcs/alta", PCEnrollmentView.as_view(), name="pcs_enroll"),
    path("pcs/<uuid:agent_id>/vinculacion", PCReEnrollmentView.as_view(), name="pcs_reenroll"),
    path("pcs/<uuid:agent_id>/cancelar-instalacion", PCEnrollmentCancelView.as_view(), name="pcs_cancel_enrollment"),
    path("internal/pcs/confirmar", PCPairingConfirmView.as_view(), name="pcs_pair_confirm"),
    path("internal/pcs/vincular", PCPairingExchangeView.as_view(), name="pcs_pair"),
    path("almacenamiento", StorageStatusView.as_view(), name="storage_status"),
    path("almacenamiento/vista-previa", StoragePreviewView.as_view(), name="storage_preview"),
    path("almacenamiento/liberar", StorageCleanupView.as_view(), name="storage_cleanup"),
    path("configuracion-operativa", OperationalConfigView.as_view(), name="configuracion_operativa"),
    path("pcs", AgentRegistrationListCreateView.as_view(), name="pcs"),
    path("pcs/<uuid:agent_id>/revocar",AgentRegistrationRevokeView.as_view(),name="pcs_revoke",),
    path("pcs/<uuid:agent_id>/renovar",AgentRegistrationRenewView.as_view(),name="pcs_renew",),
    path("pcs/<uuid:agent_id>/historial",AgentConnectivityHistoryView.as_view(),name="pcs_connectivity_history",),
    ]

