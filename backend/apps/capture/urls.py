from django.urls import path

from .views import FragmentUploadView, FragmentV2UploadView
from .agent_events import AgentEventsView, AgentSessionInspectionView, AgentCaptureEndedView
from .audio_tests import AudioTestView

app_name = "capture"
urlpatterns = [
    path("audio-tests/<uuid:test_id>", AudioTestView.as_view(), name="audio_test"),
    path("audio-tests/<uuid:test_id>/fragments", FragmentV2UploadView.as_view(), name="audio_test_fragment"),
    path("fragments", FragmentUploadView.as_view(), name="fragment_upload"),
    path("agent-events", AgentEventsView.as_view(), name="agent_events"),
    path("sessions/<uuid:session_id>", AgentSessionInspectionView.as_view(), name="session_inspection"),
    path("sessions/<uuid:session_id>/capture-ended", AgentCaptureEndedView.as_view(), name="capture_ended"),
]
