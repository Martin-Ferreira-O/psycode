from django.utils import timezone
from rest_framework.authentication import SessionAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication

from backend.common.errors import ServiceError

from .browser_sessions import ACCESS_COOKIE
from .repositories import AccountsRepository
from .tokens import validate_token_user


class AccountJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        if self.get_header(request) is not None:
            return super().authenticate(request)
        raw = request.COOKIES.get(ACCESS_COOKIE)
        if not raw:
            return None
        # DRF omite CsrfViewMiddleware: las cookies necesitan comprobación explícita.
        SessionAuthentication().enforce_csrf(request)
        token = self.get_validated_token(raw)
        user = self.get_user(token)
        session = AccountsRepository().find_refresh(token.get("session_jti", ""))
        if (session is None or session.user_id != user.pk or session.revoked_at
                or session.expires_at <= timezone.now()):
            raise ServiceError("AUTH_INVALID_TOKEN", "Sesión inválida", 401)
        return user, token

    def get_user(self, validated_token):
        return validate_token_user(validated_token, AccountsRepository(), "AUTH_INVALID_TOKEN")
