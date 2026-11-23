from django.urls import path

from backend.apps.operational.windows_installer import AgentWindowsUpdateView

from .views import FragmentUploadView, AgentConfigurationView
from .agent_events import AgentEventsView, AgentSessionInspectionView, AgentCaptureEndedView
from .audio_tests import AudioTestView
from .pairing import PCPairingConfirmView, PCPairingExchangeView

app_name = "capture"
urlpatterns = [
    path("audio-tests/<uuid:test_id>", AudioTestView.as_view(), name="audio_test"),
    path("audio-tests/<uuid:test_id>/fragments", FragmentUploadView.as_view(), name="audio_test_fragment"),
    path("fragments", FragmentUploadView.as_view(), name="fragment_upload"),
    path("agent-updates/windows-x64", AgentWindowsUpdateView.as_view(), name="agent_windows_update"),
    path("agent-updates/windows-x64/<str:version>", AgentWindowsUpdateView.as_view(), name="agent_windows_update_download"),
    path("agent-events", AgentEventsView.as_view(), name="agent_events"),
    path("sessions/<uuid:session_id>", AgentSessionInspectionView.as_view(), name="session_inspection"),
    path("sessions/<uuid:session_id>/capture-ended", AgentCaptureEndedView.as_view(), name="capture_ended"),
    path("pcs/confirmar", PCPairingConfirmView.as_view(), name="pcs_pair_confirm"),
    path("pcs/vincular", PCPairingExchangeView.as_view(), name="pcs_pair"),
    path("pcs/<uuid:agent_id>/config", AgentConfigurationView.as_view(), name="agent_config"),
]
