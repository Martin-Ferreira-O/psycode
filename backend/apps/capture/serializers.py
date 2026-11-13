from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers
from backend.common.boxes import BOX_PATTERN
from .models import AgentConfiguration, ConfigurationState
from .protocol import configuration, CONFIG_KEYS


ALLOWED_REMOTE_CONFIG_KEYS = CONFIG_KEYS


class FragmentSerializer(serializers.Serializer):
    archivo = serializers.FileField(allow_empty_file=True)
    box = serializers.RegexField(regex=rf"^{BOX_PATTERN}$", max_length=16)
    session_id = serializers.UUIDField()
    secuencia = serializers.RegexField(r"\A(0|[1-9][0-9]{0,18})\Z", max_length=19, trim_whitespace=False)
    formato = serializers.CharField(max_length=16, trim_whitespace=False)
    checksum = serializers.RegexField(r"\A[0-9a-f]{64}\Z", min_length=64, max_length=64, trim_whitespace=False)
    captured_at = serializers.CharField(max_length=40, trim_whitespace=False)

    def to_internal_value(self, data):
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
    name = serializers.CharField(
        max_length=100,
        allow_blank=False,
        trim_whitespace=True,
    )
    box = serializers.RegexField(regex=rf"^{BOX_PATTERN}$", max_length=16)

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("El nombre del PC es obligatorio.")
        return value


class AgentConfigurationSerializer(serializers.ModelSerializer):
    desired_config = serializers.JSONField(required=True)
    base_version = serializers.IntegerField(write_only=True, required=False, min_value=0)
    expected_version = serializers.IntegerField(write_only=True, required=False, min_value=0)
    desired_version = serializers.IntegerField(source="version", read_only=True)
    effective_version = serializers.SerializerMethodField()
    effective_local_revision = serializers.SerializerMethodField()

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
            "desired_version", "effective_version", "effective_local_revision", "source", "local_revision",
        ]
        read_only_fields = [
            "config_id",
            "version",
            "effective_config",
            "state",
            "error_code",
            "created_at",
            "updated_at",
            "source", "local_revision",
        ]

    def validate_desired_config(self, value):
        try:
            return configuration(value)
        except ValueError:
            raise serializers.ValidationError("Parámetros de configuración inválidos.") from None

    def validate(self, attrs):
        versions = [self.initial_data[name] for name in ("base_version", "expected_version", "version")
                    if name in self.initial_data]
        if any(type(v) is not int or v < 0 or v > 9223372036854775806 for v in versions):
            raise serializers.ValidationError("Versión base inválida.")
        if versions and any(v != versions[0] for v in versions):
            raise serializers.ValidationError("Las versiones base no coinciden.")
        if versions:
            attrs["base_version"] = versions[0]
        return attrs

    def _applied(self, instance):
        if "applied" not in self.context:
            self.context["applied"] = instance.agent.configurations.filter(
                state=ConfigurationState.APPLIED,effective_config__has_key="heartbeat_interval").order_by("-version").first()
        return self.context["applied"]

    def get_effective_version(self, instance):
        applied = self._applied(instance)
        return applied.version if applied else None

    def get_effective_local_revision(self, instance):
        applied = self._applied(instance)
        return applied.local_revision if applied else 0

    def to_representation(self, instance):
        data = super().to_representation(instance)
        applied = self._applied(instance)
        data["effective_config"] = configuration(applied.effective_config, effective=True) if applied else {}
        data["desired_config"] = {key:value for key,value in data["desired_config"].items() if key in CONFIG_KEYS}
        current = instance.agent.configurations.order_by("-version").first()
        data["version"] = current.version if current else 0
        return data
