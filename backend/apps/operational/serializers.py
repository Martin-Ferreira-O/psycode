import math
import re
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import URLValidator
from rest_framework import serializers
from backend.apps.accounts.serializers import StrictSerializer, StrictStringField
from backend.apps.agenda.models import SmileRoom
from backend.apps.capture.models import AgentRegistration
from backend.common.boxes import is_box, registrable_boxes
from .models import AudioChunkMode, JevVersion, NotificationMode, SMILE_FIELDS, SMILE_TIMEZONE, SmileFormat, SpeechmaticsModel


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


class StrictChoiceField(serializers.ChoiceField):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid_choice", input=data)
        return super().to_internal_value(data)


class ThresholdField(serializers.FloatField):
    def to_internal_value(self, data):
        if type(data) not in (int, float):
            self.fail("invalid")
        if isinstance(data, float) and not math.isfinite(data):
            self.fail("invalid")
        return data


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
    jev_model = StrictChoiceField(choices=JevVersion.values, required=False)
    jev_threshold = ThresholdField(min_value=0, max_value=1, required=False)
    speechmatics_model = StrictChoiceField(choices=SpeechmaticsModel.values, required=False)
    smile_collector_id = StrictStringField(max_length=36, allow_null=True, required=False)
    smile_source = StrictStringField(max_length=64, required=False)
    smile_url = StrictStringField(max_length=2048, allow_blank=True, required=False)
    smile_interval = StrictIntegerField(min_value=1, max_value=86400, required=False)
    smile_timeout = StrictIntegerField(min_value=1, max_value=3600, required=False)
    smile_request_timeout = StrictIntegerField(min_value=1, max_value=300, required=False)
    smile_format = serializers.ChoiceField(choices=SmileFormat.values, required=False)
    smile_timezone = StrictChoiceField(choices=[SMILE_TIMEZONE], required=False)
    smile_boxes = serializers.ListField(child=StrictStringField(max_length=16), max_length=500, required=False)

    def validate_smile_collector_id(self, value):
        from backend.apps.capture.protocol import identifier
        if value is None:
            return None
        try:
            return identifier(value)
        except ValueError:
            raise serializers.ValidationError("Selecciona un PC registrado.") from None

    def validate_smile_source(self, value):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
            raise serializers.ValidationError("Usa solo letras ASCII, números, guiones o guiones bajos.")
        return value

    def validate_smile_url(self, value):
        if not value:
            return value
        try:
            URLValidator(schemes=["https"])(value)
            parsed = urlsplit(value)
            if (parsed.username is not None or parsed.password is not None or "?" in value or "#" in value
                    or parsed.port == 0 or not parsed.path.rstrip("/").endswith("/index.php") or "\\" in value
                    or len(value.rstrip("/")) >= 2048):
                raise ValueError
        except (DjangoValidationError, ValueError):
            raise serializers.ValidationError("Ingresa una URL HTTPS de Smile terminada en /index.php/, sin credenciales ni parámetros.") from None
        return parsed._replace(path=parsed.path.rstrip("/") + "/").geturl()

    def validate_smile_boxes(self, values):
        if any(not is_box(value) for value in values) or len(values) != len(set(values)):
            raise serializers.ValidationError("Selecciona boxes válidos y sin duplicados.")
        if set(values) - set(registrable_boxes()):
            raise serializers.ValidationError("El alcance incluye un box desconocido.")
        return sorted(values, key=lambda box: int(box[4:]))

    def _smile_errors(self, data):
        if not set(data).intersection(SMILE_FIELDS):
            return {}
        profile = {field: data.get(field, getattr(self.instance, field)) for field in SMILE_FIELDS}
        collector = profile["smile_collector_id"]
        boxes = profile["smile_boxes"]
        errors = {}
        if profile["smile_request_timeout"] > profile["smile_timeout"]:
            errors["smile_request_timeout"] = "El tiempo de red debe ser igual o menor que el de ejecución."
        if collector:
            if "smile_collector_id" in data:
                agent = AgentRegistration.objects.filter(pk=collector).first()
                if not agent or not agent.is_active or not agent.token_sha256:
                    errors["smile_collector_id"] = "Selecciona un PC con credencial activa."
            if not profile["smile_url"]:
                errors["smile_url"] = "Ingresa la URL para activar el colector."
            if not boxes:
                errors["smile_boxes"] = "Selecciona al menos un box para el alcance."
            elif profile["smile_format"] == SmileFormat.EXCEL and len(boxes) != 1:
                errors["smile_boxes"] = "Selecciona un solo box para Excel."
            if SmileRoom.objects.filter(box__in=boxes).exclude(source=profile["smile_source"]).exists():
                errors["smile_source"] = "Usa la fuente asociada a las salas seleccionadas en el catálogo."
        return errors

    def validate(self, data):
        data.pop("smile_timezone", None)
        for field in ("primary_email", "backup_email"):
            if field in data:
                data[field] = data[field].strip().lower()

        mode = data.get("notification_mode", getattr(
            self.instance, "notification_mode", NotificationMode.DISTRIBUTION_LIST,
        ))
        backup_enabled = data.get("backup_enabled", getattr(self.instance, "backup_enabled", False))
        errors = self._smile_errors(data)
        processing_or_smile = {"jev_model", "jev_threshold", "speechmatics_model", *SMILE_FIELDS}
        for field, active in (
            ("primary_email", mode == NotificationMode.DISTRIBUTION_LIST),
            ("backup_email", backup_enabled),
        ):
            if active and set(data) - processing_or_smile:
                value = data.get(field, getattr(self.instance, field, ""))
                try:
                    serializers.EmailField(max_length=254).run_validation(value)
                except serializers.ValidationError as exc:
                    errors[field] = exc.detail
        if errors:
            raise serializers.ValidationError(errors)
        return data
