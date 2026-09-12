from rest_framework_simplejwt.authentication import JWTAuthentication

from .repositories import AccountsRepository
from .tokens import validate_token_user


class AccountJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        return validate_token_user(validated_token, AccountsRepository(), "AUTH_INVALID_TOKEN")
