import hashlib
import hmac
import secrets
from datetime import datetime, timezone as datetime_timezone
from datetime import timedelta
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

from .tokens import credential_hash, validate_token_user


def reset_digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


class AccountsService:
    def __init__(self, repository, email_client):
        self.repository = repository
        self.email_client = email_client

    def _issue_pair(self, user):
        refresh = RefreshToken.for_user(user)
        self.repository.create_refresh(user, refresh["jti"], datetime.fromtimestamp(refresh["exp"], tz=datetime_timezone.utc))
        return {"access_token": str(refresh.access_token), "refresh_token": str(refresh), "token_type": "Bearer", "expires_in": 3600}

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
            if session is None or session.user_id != user.pk or session.revoked_at or session.expires_at <= timezone.now():
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
    def get_current_user(user):
        return {"id": str(user.pk), "usuario": user.username, "nombre": user.get_full_name(), "correo": user.email, "activo": user.is_active}

    def request_password_reset(self, correo, client_ip=""):
        correo = correo.strip().lower()
        now = timezone.now()
        window = timedelta(seconds=settings.PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS)
        secret = settings.SECRET_KEY.encode()
        ip_key = hmac.new(secret, ("ip:" + client_ip).encode(), hashlib.sha256).hexdigest()
        email_key = hmac.new(secret, ("email:" + correo).encode(), hashlib.sha256).hexdigest()
        with self.repository.atomic():
            ip_count = self.repository.count_reset_attempt(ip_key, now, window)
            email_count = (self.repository.count_reset_attempt(email_key, now, window)
                           if ip_count <= settings.PASSWORD_RESET_RATE_LIMIT_MAX else 0)
            limited = max(ip_count, email_count) > settings.PASSWORD_RESET_RATE_LIMIT_MAX
            user = self.repository.find_by_email(correo) if not limited and email_count == 1 else None
            if user is not None and user.is_active:
                token = secrets.token_urlsafe(32)
                digest = reset_digest(token)
                self.repository.replace_reset(user, digest, credential_hash(user), timezone.now() + settings.PASSWORD_RESET_LIFETIME)
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
            if (record is None or record.expires_at <= timezone.now()
                    or not constant_time_compare(record.credential_hash, credential_hash(record.user))):
                raise ServiceError("AUTH_INVALID_RESET_TOKEN", "Token de recuperación inválido", 400)
            if not record.user.is_active:
                raise ServiceError("AUTH_USER_INACTIVE", "Usuario inactivo", 403)
            try:
                validate_password(nueva_password, record.user)
            except ValidationError as exc:
                raise ServiceError("VALIDATION_ERROR", "Contraseña no aceptable", 400, {"fields": {"nueva_password": exc.messages}}) from None
            self.repository.change_password(record.user, nueva_password)
