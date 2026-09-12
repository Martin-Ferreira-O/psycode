from rest_framework import serializers


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
    password = StrictStringField(trim_whitespace=False, write_only=True)


class RefreshSerializer(StrictSerializer):
    refresh_token = StrictStringField(trim_whitespace=False, write_only=True)


class PasswordResetSerializer(StrictSerializer):
    correo = StrictStringField(max_length=254)

    def validate_correo(self, value):
        return serializers.EmailField().run_validation(value).lower()


class PasswordResetConfirmSerializer(StrictSerializer):
    token = StrictStringField(trim_whitespace=False, write_only=True)
    nueva_password = StrictStringField(trim_whitespace=False, write_only=True)
