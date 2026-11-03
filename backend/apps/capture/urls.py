from django.urls import path

from .views import FragmentUploadView
from .agent_events import AgentEventsView, AgentSessionInspectionView, AgentCaptureEndedView

app_name = "capture"
urlpatterns = [
    path("fragments", FragmentUploadView.as_view(), name="fragment_upload"),
    path("agent-events", AgentEventsView.as_view(), name="agent_events"),
    path("sessions/<uuid:session_id>", AgentSessionInspectionView.as_view(), name="session_inspection"),
    path("sessions/<uuid:session_id>/capture-ended", AgentCaptureEndedView.as_view(), name="capture_ended"),
]
