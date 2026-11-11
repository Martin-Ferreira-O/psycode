from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers
from backend.common.boxes import BOX_PATTERN


class FragmentSerializer(serializers.Serializer):
    archivo = serializers.FileField(allow_empty_file=True)
    box = serializers.RegexField(regex=rf"^{BOX_PATTERN}$", max_length=16)
    session_id = serializers.UUIDField()
    secuencia = serializers.RegexField(r"\A(0|[1-9][0-9]{0,18})\Z", max_length=19, trim_whitespace=False)
    formato = serializers.CharField(max_length=16, trim_whitespace=False)
    checksum = serializers.RegexField(r"\A[0-9a-f]{64}\Z", min_length=64, max_length=64, trim_whitespace=False)
    captured_at = serializers.CharField(max_length=40, trim_whitespace=False)

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


class FragmentV2Serializer(FragmentSerializer):
    session_start_sample = serializers.IntegerField(min_value=0, max_value=9223372036854775806)
    session_end_sample = serializers.IntegerField(min_value=1, max_value=9223372036854775806)
    new_audio_start_sample = serializers.IntegerField(min_value=0, max_value=9223372036854775806)
    sample_rate = serializers.IntegerField(min_value=16000, max_value=16000)
    chunk_samples = serializers.IntegerField(min_value=1, max_value=16000 * 600)
    overlap_samples = serializers.IntegerField(min_value=0, max_value=16000 * 600 - 1)

class AgentRegistrationCreateSerializer(serializers.Serializer):
    """Datos permitidos al registrar un nuevo PC."""

    name = serializers.CharField(
        max_length=100,
        allow_blank=False,
        trim_whitespace=True,
    )

    box = serializers.RegexField(regex=rf"^{BOX_PATTERN}$", max_length=16)

    def validate_name(self, value):
        value = value.strip()

        if not value:
            raise serializers.ValidationError(
                "El nombre del PC es obligatorio."
            )

        return value

from backend.apps.capture.models import AgentConfiguration

class AgentConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentConfiguration
        fields = ["config_id", "version", "desired_config", "effective_config", "state", "error_code", "created_at", "updated_at"]
        read_only_fields = ["config_id", "version", "effective_config", "state", "error_code", "created_at", "updated_at"]

    def validate_desired_config(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("La configuración deseada debe ser un diccionario JSON válido.")
        return value
