from django.urls import include, path, re_path

from backend.apps.accounts.urls import patterns
from backend.common.errors import not_found

from .composition import accounts_service

from backend.apps.capture.views import FragmentV2UploadView
from backend.apps.agenda.views import CollectionView, ReportView, SmileCatalogView, SmileConfigurationView
from backend.apps.agenda.collector_check import AgentSmileCheckView

urlpatterns = [
    path("api/v1/internal/smile-configuration", SmileConfigurationView.as_view()),
    path("api/v1/internal/smile-room-catalogues", SmileCatalogView.as_view()),
    path("api/v1/internal/smile-collector-check", AgentSmileCheckView.as_view()),
    path("api/v2/internal/fragments", FragmentV2UploadView.as_view()),
    path("api/v1/internal/agenda-collections", CollectionView.as_view()),
    path("api/v1/internal/agenda-reports", ReportView.as_view()),
    path("api/v1/auth/", include((patterns(accounts_service), "accounts"))),
    path("api/v1/", include("backend.apps.alerts.urls")),
    path("api/v1/dashboard/", include("backend.apps.dashboard.urls")),
    path("", include("backend.apps.web.urls")),
    path("api/v1/", include("backend.apps.operational.urls")),
    path("api/v1/internal/", include("backend.apps.capture.urls")),
    re_path(r"^.*$", not_found),
]

handler400 = "backend.common.errors.bad_request"
handler404 = "backend.common.errors.not_found"
handler500 = "backend.common.errors.server_error"
