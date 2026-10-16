import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone as datetime_timezone
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from backend.common.errors import ServiceError

from .models import Role, User
from .tokens import credential_hash, validate_token_user


def reset_digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


class AccountsService:
    def __init__(self, repository, email_client):
        self.repository = repository
        self.email_client = email_client

    def _issue_pair(self, user):
        refresh = RefreshToken.for_user(user)
        self.repository.create_refresh(
            user, refresh["jti"], datetime.fromtimestamp(refresh["exp"], tz=datetime_timezone.utc)
        )
        return {
            "access_token": str(refresh.access_token),
            "refresh_token": str(refresh),
            "token_type": "Bearer",
            "expires_in": 3600,
        }

    def login(self, usuario, password):
        # IMMEDIATE serializa cambio de contraseña y emisión/rotación en SQLite.
        with self.repository.atomic():
            user = self.repository.find_user(usuario)
            if user is None:
                make_password(password)  # Costo comparable al caso de contraseña incorrecta.
            if user is None or not user.check_password(password):
                raise ServiceError("AUTH_INVALID_CREDENTIALS", "Credenciales incorrectas", 401)
            if not user.is_active:
                raise ServiceError("AUTH_USER_INACTIVE", "Usuario inactivo", 403)
            return self._issue_pair(user)

    @staticmethod
    def _parse_refresh(raw):
        try:
            return RefreshToken(raw)
        except (TokenError, ValueError, TypeError):
            raise ServiceError("AUTH_INVALID_REFRESH_TOKEN", "Refresh inválido", 401) from None

    def refresh(self, refresh_token):
        token = self._parse_refresh(refresh_token)
        with self.repository.atomic():
            user = validate_token_user(token, self.repository, "AUTH_INVALID_REFRESH_TOKEN")
            session = self.repository.find_refresh(token["jti"])
            if (
                session is None
                or session.user_id != user.pk
                or session.revoked_at
                or session.expires_at <= timezone.now()
            ):
                raise ServiceError("AUTH_INVALID_REFRESH_TOKEN", "Refresh inválido", 401)
            self.repository.revoke_refresh(session)
            return self._issue_pair(user)

    def logout(self, user, refresh_token):
        token = self._parse_refresh(refresh_token)
        with self.repository.atomic():
            owner = validate_token_user(token, self.repository, "AUTH_INVALID_REFRESH_TOKEN")
            if owner.pk != user.pk:
                raise ServiceError("AUTH_FORBIDDEN", "Refresh no pertenece al usuario", 403)
            session = self.repository.find_refresh(token["jti"])
            if session is None or session.user_id != owner.pk or session.expires_at <= timezone.now():
                raise ServiceError("AUTH_INVALID_REFRESH_TOKEN", "Refresh inválido", 401)
            if session.revoked_at is None:
                self.repository.revoke_refresh(session)

    @staticmethod
    def _format_user(user):
        return {
            "id": str(user.pk),
            "usuario": user.username,
            "nombre": user.get_full_name() or user.username,
            "correo": user.email,
            "rol": getattr(user, "role", Role.SUPERVISOR),
            "activo": user.is_active,
        }

    @staticmethod
    def get_current_user(user):
        return {
            "id": str(user.pk),
            "usuario": user.username,
            "nombre": user.get_full_name(),
            "correo": user.email,
            "rol": getattr(user, "role", Role.SUPERVISOR),
            "activo": user.is_active,
        }

    def request_password_reset(self, correo, client_ip=""):
        correo = correo.strip().lower()
        now = timezone.now()
        window = timedelta(seconds=settings.PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS)
        secret = settings.SECRET_KEY.encode()
        ip_key = hmac.new(secret, ("ip:" + client_ip).encode(), hashlib.sha256).hexdigest()
        email_key = hmac.new(secret, ("email:" + correo).encode(), hashlib.sha256).hexdigest()
        with self.repository.atomic():
            ip_count = self.repository.count_reset_attempt(ip_key, now, window)
            email_count = (
                self.repository.count_reset_attempt(email_key, now, window)
                if ip_count <= settings.PASSWORD_RESET_RATE_LIMIT_MAX
                else 0
            )
            limited = max(ip_count, email_count) > settings.PASSWORD_RESET_RATE_LIMIT_MAX
            user = self.repository.find_by_email(correo) if not limited and email_count == 1 else None
            if user is not None and user.is_active:
                token = secrets.token_urlsafe(32)
                digest = reset_digest(token)
                self.repository.replace_reset(
                    user, digest, credential_hash(user), timezone.now() + settings.PASSWORD_RESET_LIFETIME
                )
        if limited:
            raise ServiceError("PASSWORD_RESET_RATE_LIMITED", "Demasiadas solicitudes. Intenta más tarde.", 429)
        if user is None or not user.is_active:
            return
        # Nunca sostener el bloqueo de escritura de SQLite durante la red.
        link = settings.FRONTEND_BASE_URL + settings.PASSWORD_RESET_PATH + "?" + urlencode({"token": token})
        try:
            self.email_client.send_password_reset(user.email, link)
        except ServiceError:
            self.repository.discard_reset(digest)
            # La respuesta pública no distingue la existencia ni el estado del transporte.
            return

    def confirm_password_reset(self, token, nueva_password):
        with self.repository.atomic():
            record = self.repository.find_reset(reset_digest(token))
            if (
                record is None
                or record.expires_at <= timezone.now()
                or not constant_time_compare(record.credential_hash, credential_hash(record.user))
            ):
                raise ServiceError("AUTH_INVALID_RESET_TOKEN", "Token de recuperación inválido", 400)
            if not record.user.is_active:
                raise ServiceError("AUTH_USER_INACTIVE", "Usuario inactivo", 403)
            try:
                validate_password(nueva_password, record.user)
            except ValidationError as exc:
                raise ServiceError(
                    "VALIDATION_ERROR",
                    "Contraseña no aceptable",
                    400,
                    {"fields": {"nueva_password": exc.messages}},
                ) from None
            self.repository.change_password(record.user, nueva_password)

    # --- Módulo Administrativo de Usuarios ---

    def list_users(self, actor):
        if not (actor.is_authenticated and actor.is_active and getattr(actor, "is_admin", False)):
            raise ServiceError("AUTH_FORBIDDEN", "No tienes permisos para administrar usuarios", 403)
        users = self.repository.list_users()
        return [self._format_user(u) for u in users]

    def create_admin_user(self, actor, usuario, nombre, correo, password, rol=Role.SUPERVISOR, activo=True):
        if not (actor.is_authenticated and actor.is_active and getattr(actor, "is_admin", False)):
            raise ServiceError("AUTH_FORBIDDEN", "No tienes permisos para administrar usuarios", 403)

        correo_norm = correo.strip().lower()
        if "@" in usuario:
            raise ServiceError(
                "VALIDATION_ERROR",
                "El nombre de usuario no puede contener @.",
                400,
                {"fields": {"usuario": ["No puede contener @."]}},
            )

        with self.repository.atomic():
            if self.repository.find_by_email(correo_norm) is not None:
                raise ServiceError(
                    "VALIDATION_ERROR",
                    "Ya existe un usuario con este correo.",
                    400,
                    {"fields": {"correo": ["Ya existe un usuario con este correo."]}},
                )
            if self.repository.find_user(usuario) is not None:
                raise ServiceError(
                    "VALIDATION_ERROR",
                    "Ya existe este nombre de usuario.",
                    400,
                    {"fields": {"usuario": ["Ya existe este nombre de usuario."]}},
                )

            user_instance = User(username=usuario, email=correo_norm)
            try:
                validate_password(password, user_instance)
            except ValidationError as exc:
                raise ServiceError(
                    "VALIDATION_ERROR",
                    "Contraseña no aceptable",
                    400,
                    {"fields": {"password": exc.messages}},
                ) from None

            parts = nombre.strip().split(" ", 1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else ""

            user = self.repository.create_user(
                username=usuario,
                email=correo_norm,
                first_name=first_name,
                last_name=last_name,
                password=password,
                role=rol,
                is_active=activo,
            )
            return self._format_user(user)

    def update_admin_user(self, actor, user_id, **fields):
        if not (actor.is_authenticated and actor.is_active and getattr(actor, "is_admin", False)):
            raise ServiceError("AUTH_FORBIDDEN", "No tienes permisos para administrar usuarios", 403)

        with self.repository.atomic():
            target_user = self.repository.find_by_id(user_id)
            if target_user is None:
                raise ServiceError("RESOURCE_NOT_FOUND", "Usuario no encontrado", 404)

            # Impedir que un administrador se desactive a sí mismo o se quite permisos
            if str(target_user.pk) == str(actor.pk):
                if "activo" in fields and not fields["activo"]:
                    raise ServiceError(
                        "VALIDATION_ERROR",
                        "No puedes desactivar tu propia cuenta.",
                        400,
                        {"fields": {"activo": ["No puedes desactivar tu propia cuenta."]}},
                    )
                if "rol" in fields and fields["rol"] != Role.ADMIN:
                    raise ServiceError(
                        "VALIDATION_ERROR",
                        "No puedes revocar tu propio rol de administrador.",
                        400,
                        {"fields": {"rol": ["No puedes revocar tu propio rol de administrador."]}},
                    )

            db_fields = {}
            if "correo" in fields:
                correo_norm = fields["correo"].strip().lower()
                existing = self.repository.find_by_email(correo_norm)
                if existing and str(existing.pk) != str(target_user.pk):
                    raise ServiceError(
                        "VALIDATION_ERROR",
                        "Ya existe un usuario con este correo.",
                        400,
                        {"fields": {"correo": ["Ya existe un usuario con este correo."]}},
                    )
                db_fields["email"] = correo_norm

            if "nombre" in fields:
                parts = fields["nombre"].strip().split(" ", 1)
                db_fields["first_name"] = parts[0]
                db_fields["last_name"] = parts[1] if len(parts) > 1 else ""

            if "rol" in fields:
                db_fields["role"] = fields["rol"]

            if "activo" in fields:
                db_fields["is_active"] = fields["activo"]

            updated_user = self.repository.update_user(target_user, **db_fields)
            return self._format_user(updated_user)

    def toggle_user_active(self, actor, user_id):
        if not (actor.is_authenticated and actor.is_active and getattr(actor, "is_admin", False)):
            raise ServiceError("AUTH_FORBIDDEN", "No tienes permisos para administrar usuarios", 403)

        with self.repository.atomic():
            target_user = self.repository.find_by_id(user_id)
            if target_user is None:
                raise ServiceError("RESOURCE_NOT_FOUND", "Usuario no encontrado", 404)

            if str(target_user.pk) == str(actor.pk):
                raise ServiceError(
                    "VALIDATION_ERROR",
                    "No puedes modificar el estado activo de tu propia cuenta.",
                    400,
                    {"fields": {"activo": ["No puedes modificar el estado activo de tu propia cuenta."]}},
                )

            target_user = self.repository.update_user(target_user, is_active=not target_user.is_active)
            return self._format_user(target_user)