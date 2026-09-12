from django.urls import path

from . import views

app_name = "accounts"


def patterns(service_factory):
    return [
        path("login", views.LoginView.as_view(service_factory=service_factory), name="login"),
        path("refresh", views.RefreshView.as_view(service_factory=service_factory), name="refresh"),
        path("logout", views.LogoutView.as_view(service_factory=service_factory), name="logout"),
        path("me", views.MeView.as_view(service_factory=service_factory), name="me"),
        path("password-reset", views.PasswordResetView.as_view(service_factory=service_factory), name="password_reset"),
        path("password-reset/confirm", views.PasswordResetConfirmView.as_view(service_factory=service_factory), name="password_reset_confirm"),
    ]
