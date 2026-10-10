import time
from uuid import UUID

from rest_framework import serializers
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from backend.common.audit import AuditWriter
from backend.common.responses import success_response

from .serializers import (
    AdminUserCreateSerializer,
    AdminUserUpdateSerializer,
    LoginSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetSerializer,
    RefreshSerializer,
)


class AccountsView(APIView):
    service_factory = None  # Inyectada por config; no importar composición desde la app.

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if request.query_params:
            raise serializers.ValidationError({"query": ["Esta operación no acepta parámetros de consulta."]})
        if request.method in {"GET", "HEAD"} and request.body:
            raise serializers.ValidationError({"body": ["GET no acepta cuerpo."]})

    def perform(self, method, serializer_type, message, status=200, user_argument=False, client_ip=False):
        try:
            serializer = serializer_type(data=self.request.data)
            serializer.is_valid(raise_exception=True)
            kwargs = dict(serializer.validated_data)
            if user_argument:
                kwargs["user"] = self.request.user
            if client_ip:
                kwargs["client_ip"] = self.request.META.get("REMOTE_ADDR", "")
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
        started = time.monotonic()
        response = self.perform(
            "request_password_reset",
            PasswordResetSerializer,
            "Si el correo está registrado, recibirás las instrucciones para recuperar tu contraseña.",
            status=202,
            client_ip=True,
        )
        time.sleep(max(0, 0.5 - (time.monotonic() - started)))
        return response


class PasswordResetConfirmView(PublicAccountsView):
    def post(self, request):
        return self.perform("confirm_password_reset", PasswordResetConfirmSerializer, "Contraseña actualizada")


# --- Vistas Administrativas ---


class ProtectedAccountsView(AccountsView):
    permission_classes = [IsAuthenticated]


class AdminUsersListView(ProtectedAccountsView):
    def get(self, request):
        actor_id = getattr(request.user, "pk", None)
        try:
            data = self.service_factory().list_users(actor=request.user)
            AuditWriter.record("admin.users.list", "success", actor_id=actor_id)
            return success_response(data, "Lista de usuarios")
        except Exception as exc:
            AuditWriter.record(
                "admin.users.list",
                "failure",
                actor_id=actor_id,
                error_code=getattr(exc, "code", "REQUEST_FAILED"),
            )
            raise

    def post(self, request):
        actor_id = getattr(request.user, "pk", None)
        try:
            serializer = AdminUserCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = self.service_factory().create_admin_user(
                actor=request.user,
                **serializer.validated_data,
            )
            AuditWriter.record("admin.users.create", "success", actor_id=actor_id)
            return success_response(data, "Usuario registrado", status=201)
        except Exception as exc:
            AuditWriter.record(
                "admin.users.create",
                "failure",
                actor_id=actor_id,
                error_code=getattr(exc, "code", "REQUEST_FAILED"),
            )
            raise


class AdminUserDetailView(ProtectedAccountsView):
    @staticmethod
    def _validate_uuid(user_id):
        try:
            return UUID(str(user_id))
        except (ValueError, TypeError):
            raise serializers.ValidationError({"user_id": ["Identificador de usuario inválido."]})

    def patch(self, request, user_id):
        actor_id = getattr(request.user, "pk", None)
        valid_uuid = self._validate_uuid(user_id)
        try:
            serializer = AdminUserUpdateSerializer(data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            data = self.service_factory().update_admin_user(
                actor=request.user,
                user_id=valid_uuid,
                **serializer.validated_data,
            )
            AuditWriter.record("admin.users.update", "success", actor_id=actor_id)
            return success_response(data, "Usuario actualizado")
        except Exception as exc:
            AuditWriter.record(
                "admin.users.update",
                "failure",
                actor_id=actor_id,
                error_code=getattr(exc, "code", "REQUEST_FAILED"),
            )
            raise


class AdminUserToggleActiveView(ProtectedAccountsView):
    def patch(self, request, user_id):
        actor_id = getattr(request.user, "pk", None)
        try:
            valid_uuid = UUID(str(user_id))
        except (ValueError, TypeError):
            raise serializers.ValidationError({"user_id": ["Identificador de usuario inválido."]})

        try:
            data = self.service_factory().toggle_user_active(actor=request.user, user_id=valid_uuid)
            AuditWriter.record("admin.users.toggle_active", "success", actor_id=actor_id)
            return success_response(data, "Estado de usuario actualizado")
        except Exception as exc:
            AuditWriter.record(
                "admin.users.toggle_active",
                "failure",
                actor_id=actor_id,
                error_code=getattr(exc, "code", "REQUEST_FAILED"),
            )
            raise