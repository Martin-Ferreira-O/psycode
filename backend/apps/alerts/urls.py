from django.urls import path

from .audit_api import AuditExportView, AuditListView
from .views import AlertDetailView, AlertEvaluationView,  AlertExportView, AlertListView 

app_name = "alerts"

urlpatterns = [
    path("audit-events/export", AuditExportView.as_view(), name="audit-export"),
    path("audit-events", AuditListView.as_view(), name="audit-list"),
    path("alerts", AlertListView.as_view(), name="list"),
    path("alerts/export", AlertExportView.as_view(), name="export"),
    path("alerts/<str:alerta_id>/evaluacion", AlertEvaluationView.as_view(), name="evaluation"),
    path("alerts/<str:alerta_id>", AlertDetailView.as_view(), name="detail"),
]
