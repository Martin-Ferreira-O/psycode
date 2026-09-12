from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from backend.common.audit import AuditWriter
from backend.common.responses import success_response

from .serializers import LoginSerializer, PasswordResetConfirmSerializer, PasswordResetSerializer, RefreshSerializer


class AccountsView(APIView):
    service_factory = None  # Inyectada por config; no importar composición desde la app.

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if request.query_params:
            raise serializers.ValidationError({"query": ["Esta operación no acepta parámetros de consulta."]})
        if request.method in {"GET", "HEAD"} and request.body:
            raise serializers.ValidationError({"body": ["GET no acepta cuerpo."]})

    def perform(self, method, serializer_type, message, status=200, user_argument=False):
        try:
            serializer = serializer_type(data=self.request.data)
            serializer.is_valid(raise_exception=True)
            kwargs = dict(serializer.validated_data)
            if user_argument:
                kwargs["user"] = self.request.user
            data = getattr(self.service_factory(), method)(**kwargs)
        except Exception as exc:
            AuditWriter.record("auth." + method, "failure", error_code=getattr(exc, "code", "REQUEST_FAILED"))
            raise
        actor = getattr(self.request.user, "pk", None)
        AuditWriter.record("auth." + method, "success", actor_id=actor)
        return success_response(data if data is not None else {}, message, status)


class PublicAccountsView(AccountsView):
    authentication_classes = []
    permission_classes = [AllowAny]


class LoginView(PublicAccountsView):
    def post(self, request):
        return self.perform("login", LoginSerializer, "Sesión iniciada")


class RefreshView(PublicAccountsView):
    def post(self, request):
        return self.perform("refresh", RefreshSerializer, "Sesión renovada")


class LogoutView(AccountsView):
    def post(self, request):
        return self.perform("logout", RefreshSerializer, "Sesión cerrada", status=204, user_argument=True)


class MeView(AccountsView):
    def get(self, request):
        return success_response(self.service_factory().get_current_user(request.user), "Usuario autenticado")


class PasswordResetView(PublicAccountsView):
    def post(self, request):
        return self.perform("request_password_reset", PasswordResetSerializer, "Instrucciones enviadas", status=202)


class PasswordResetConfirmView(PublicAccountsView):
    def post(self, request):
        return self.perform("confirm_password_reset", PasswordResetConfirmSerializer, "Contraseña actualizada")
