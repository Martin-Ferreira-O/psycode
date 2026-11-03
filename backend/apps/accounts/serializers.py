from rest_framework import serializers

from .models import Role


class StrictStringField(serializers.CharField):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError({"non_field_errors": ["Se requiere un objeto JSON."]})
        extra = set(data) - set(self.fields)
        if extra:
            raise serializers.ValidationError({key: ["Campo no permitido."] for key in sorted(extra)})
        return super().to_internal_value(data)


class LoginSerializer(StrictSerializer):
    usuario = StrictStringField(max_length=254)
    password = StrictStringField(max_length=1024, trim_whitespace=False, write_only=True)


class RefreshSerializer(StrictSerializer):
    refresh_token = StrictStringField(max_length=4096, trim_whitespace=False, write_only=True)


class PasswordResetSerializer(StrictSerializer):
    correo = StrictStringField(max_length=254)

    def validate_correo(self, value):
        return serializers.EmailField().run_validation(value).lower()


class PasswordResetConfirmSerializer(StrictSerializer):
    token = StrictStringField(max_length=128, trim_whitespace=False, write_only=True)
    nueva_password = StrictStringField(max_length=1024, trim_whitespace=False, write_only=True)



class AdminUserCreateSerializer(StrictSerializer):
    usuario = StrictStringField(max_length=150)
    nombre = StrictStringField(max_length=150)
    correo = StrictStringField(max_length=254)
    password = StrictStringField(max_length=1024, trim_whitespace=False, write_only=True)
    rol = serializers.ChoiceField(choices=Role.choices, default=Role.SUPERVISOR)
    activo = serializers.BooleanField(default=True)

    def validate_correo(self, value):
        return serializers.EmailField().run_validation(value).lower()


class AdminUserUpdateSerializer(StrictSerializer):
    nombre = StrictStringField(max_length=150, required=False)
    correo = StrictStringField(max_length=254, required=False)
    rol = serializers.ChoiceField(choices=Role.choices, required=False)
    activo = serializers.BooleanField(required=False)

    def validate_correo(self, value):
        return serializers.EmailField().run_validation(value).lower()
