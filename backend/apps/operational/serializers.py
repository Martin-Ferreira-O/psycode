from rest_framework import serializers
from backend.apps.accounts.serializers import StrictSerializer, StrictStringField
from .models import AudioChunkMode, NotificationMode


class AgentRegistrationRenameSerializer(StrictSerializer):
    name = StrictStringField(max_length=100)


class StrictBooleanField(serializers.BooleanField):
    def to_internal_value(self, data):
        if not isinstance(data, bool):
            self.fail("invalid", input=data)
        return super().to_internal_value(data)


class StrictIntegerField(serializers.IntegerField):
    def to_internal_value(self, data):
        if type(data) is not int:
            self.fail("invalid")
        return super().to_internal_value(data)


class OperationalConfigSerializer(StrictSerializer):
    audio_chunk_duration = StrictIntegerField(min_value=10, required=False)
    audio_chunk_mode = serializers.ChoiceField(choices=AudioChunkMode.choices, required=False)
    enabled_days = serializers.ListField(child=serializers.IntegerField(min_value=0, max_value=6), required=False)
    open_time = StrictStringField(max_length=5, required=False)
    close_time = StrictStringField(max_length=5, required=False)
    notification_mode = serializers.ChoiceField(choices=NotificationMode.choices, required=False)
    # El formato de correo se valida únicamente si el destino está activo.
    primary_email = StrictStringField(max_length=254, allow_blank=True, required=False)
    backup_enabled = StrictBooleanField(required=False)
    backup_email = StrictStringField(max_length=254, allow_blank=True, required=False)

    def validate(self, data):
        for field in ("primary_email", "backup_email"):
            if field in data:
                data[field] = data[field].strip().lower()

        mode = data.get("notification_mode", getattr(
            self.instance, "notification_mode", NotificationMode.DISTRIBUTION_LIST,
        ))
        backup_enabled = data.get("backup_enabled", getattr(self.instance, "backup_enabled", False))
        errors = {}
        for field, active in (
            ("primary_email", mode == NotificationMode.DISTRIBUTION_LIST),
            ("backup_email", backup_enabled),
        ):
            if active:
                value = data.get(field, getattr(self.instance, field, ""))
                try:
                    serializers.EmailField(max_length=254).run_validation(value)
                except serializers.ValidationError as exc:
                    errors[field] = exc.detail
        if errors:
            raise serializers.ValidationError(errors)
        return data
