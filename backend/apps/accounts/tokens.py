"""Validación común de identidad y versión de credencial de JWT."""
import uuid

from django.utils.crypto import constant_time_compare
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.utils import get_md5_hash_password

from backend.common.errors import ServiceError


def credential_hash(user):
    # Huella del hash Django, no se calcula sobre la contraseña en claro.
    return get_md5_hash_password(user.password)


def validate_token_user(token, repository, error_code):
    try:
        user_id = uuid.UUID(str(token[api_settings.USER_ID_CLAIM]))
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ServiceError(error_code, "Token inválido", 401) from None
    user = repository.find_by_id(user_id)
    if user is None or not constant_time_compare(token.get(api_settings.REVOKE_TOKEN_CLAIM, ""), credential_hash(user)):
        raise ServiceError(error_code, "Token inválido", 401)
    if not user.is_active:
        raise ServiceError("AUTH_USER_INACTIVE", "Usuario inactivo", 403)
    return user
