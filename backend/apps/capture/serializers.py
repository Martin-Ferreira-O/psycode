from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers
from backend.common.boxes import BOX_PATTERN
from .models import AgentConfiguration


ALLOWED_REMOTE_CONFIG_KEYS = {
    "audio_chunk_duration",
    "audio_chunk_mode",
    "audio_chunk_overlap",
    "analysis_unit",
    "sample_rate",
    "chunk_samples",
    "overlap_samples",
    "heartbeat_interval",
    "sync_interval",
    "log_level",
    "rtsp_url",
    "obs_host",
    "obs_port",
    "qa",
    "example",
}


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
    chunk_samples = serializers.IntegerField(min_value=1, max_value=9223372036854775806)
    overlap_samples = serializers.IntegerField(min_value=0, max_value=9223372036854775806 - 1)


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


class AgentConfigurationSerializer(serializers.ModelSerializer):
    desired_config = serializers.JSONField(required=True)
    base_version = serializers.IntegerField(write_only=True, required=False, min_value=0)
    expected_version = serializers.IntegerField(write_only=True, required=False, min_value=0)

    class Meta:
        model = AgentConfiguration
        fields = [
            "config_id",
            "version",
            "desired_config",
            "effective_config",
            "state",
            "error_code",
            "created_at",
            "updated_at",
            "base_version",
            "expected_version",
        ]
        read_only_fields = [
            "config_id",
            "version",
            "effective_config",
            "state",
            "error_code",
            "created_at",
            "updated_at",
        ]

    def validate_desired_config(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("La configuración deseada debe ser un diccionario JSON válido.")

        unknown_keys = set(value.keys()) - ALLOWED_REMOTE_CONFIG_KEYS
        if unknown_keys:
            raise serializers.ValidationError(
                f"Parámetros de configuración no permitidos: {', '.join(sorted(unknown_keys))}."
            )

        for key, item in value.items():
            if key == "audio_chunk_duration":
                if isinstance(item, bool) or not isinstance(item, int) or item < 10 or item > 3600:
                    raise serializers.ValidationError(
                        "El parámetro audio_chunk_duration debe ser un entero positivo entre 10 y 3600 segundos."
                    )
            elif key in {"audio_chunk_overlap", "overlap_samples"}:
                if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                    raise serializers.ValidationError(f"El parámetro {key} no puede ser negativo.")
            elif key in {"sample_rate", "chunk_samples", "heartbeat_interval", "sync_interval", "obs_port", "qa"}:
                if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
                    raise serializers.ValidationError(f"El parámetro {key} debe ser un entero positivo.")
            elif key == "audio_chunk_mode":
                if item not in {"fixed", "session"}:
                    raise serializers.ValidationError("El parámetro audio_chunk_mode debe ser 'fixed' o 'session'.")
            elif key == "analysis_unit":
                if item not in {"fragment", "block", "session"}:
                    raise serializers.ValidationError("El parámetro analysis_unit no es válido.")

        return value