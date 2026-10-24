from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers


class FragmentSerializer(serializers.Serializer):
    archivo = serializers.FileField(allow_empty_file=True)
    box = serializers.ChoiceField(choices=[f"box-{n}" for n in range(3, 8)])
    session_id = serializers.UUIDField()
    secuencia = serializers.RegexField(r"^(0|[1-9][0-9]{0,18})$", max_length=19)
    formato = serializers.CharField(max_length=16)
    checksum = serializers.RegexField(r"^[0-9a-f]{64}$", min_length=64, max_length=64)
    captured_at = serializers.CharField(max_length=40)

    def to_internal_value(self, data):
        # No reflejar nombres de campos, valores ni nombres de archivos recibidos.
        if set(data) != set(self.fields) or any(len(data.getlist(key)) != 1 for key in data):
            raise serializers.ValidationError({"non_field_errors": ["Campos inválidos."]})
        return super().to_internal_value(data)

    def validate_secuencia(self, value):
        value = int(value)
        if value > 9223372036854775806:
            raise serializers.ValidationError("Secuencia inválida.")
        return value

    def validate_captured_at(self, value):
        try:
            instant = parse_datetime(value)
        except ValueError:
            instant = None
        if instant is None or timezone.is_naive(instant):
            raise serializers.ValidationError("Fecha inválida.")
        return instant
