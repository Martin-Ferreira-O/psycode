from django.urls import path
from .views import OperationalConfigView

app_name = "operational"

urlpatterns = [
    path("configuracion-operativa", OperationalConfigView.as_view(), name="configuracion_operativa"),
]