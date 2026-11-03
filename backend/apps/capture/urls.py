from django.urls import path

from .views import FragmentUploadView

app_name = "capture"
urlpatterns = [path("fragments", FragmentUploadView.as_view(), name="fragment_upload")]
