from django.urls import include, path, re_path

from backend.apps.accounts.urls import patterns
from backend.common.errors import not_found

from .composition import accounts_service

urlpatterns = [
    path("api/v1/auth/", include((patterns(accounts_service), "accounts"))),
    path("api/v1/", include("backend.apps.alerts.urls")),
    path("api/v1/dashboard/", include("backend.apps.dashboard.urls")),
    path("", include("backend.apps.web.urls")),
    path("api/v1/", include("backend.apps.operational.urls")),
    re_path(r"^.*$", not_found),
]

handler400 = "backend.common.errors.bad_request"
handler404 = "backend.common.errors.not_found"
handler500 = "backend.common.errors.server_error"
