"""Rutas pendientes; no devolver datos ficticios como si fueran reales."""
from django.urls import path

from .views import AlertDetailView, AlertEvaluationView, AlertListView

app_name = "alerts"

urlpatterns = [
    path("alerts", AlertListView.as_view(), name="list"),
    path("alerts/<str:alerta_id>", AlertDetailView.as_view(), name="detail"),
    path("alerts/<str:alerta_id>/evaluacion", AlertEvaluationView.as_view(), name="evaluation"),
]