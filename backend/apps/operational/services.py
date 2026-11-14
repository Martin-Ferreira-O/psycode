from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo
from django.db import transaction
from backend.common.errors import ServiceError
from backend.apps.capture.services import CaptureSessionService
from backend.apps.capture.legacy_registry import sync_legacy_registry
from backend.common.boxes import registrable_boxes
from .capture_authorization import BoxCaptureAuthorization, CaptureAuthorizationService
from .models import AudioChunkConfigurationChange, JevVersion, OperationalConfiguration, SMILE_FIELDS, SMILE_TIMEZONE, SmileFormat, SpeechmaticsModel
from .serializers import OperationalConfigSerializer
from .smile_configuration import collector_options

SANTIAGO_TZ = ZoneInfo("America/Santiago")


class OperationalService:
    def __init__(self, agenda_service=None):
        self._durable_agenda = agenda_service is None
        self._capture_auth = CaptureAuthorizationService(agenda_service=agenda_service)
        self._capture_sessions = CaptureSessionService(self._capture_auth)

    def get_config(self):
        sync_legacy_registry()
        return self._serialize_config(OperationalConfiguration.load())

    @staticmethod
    def _serialize_config(config):
        return {
            "audio_chunk_duration": config.audio_chunk_duration,
            "audio_chunk_mode": config.audio_chunk_mode,
            "enabled_days": config.enabled_days,
            "open_time": config.open_time,
            "close_time": config.close_time,
            "notification_mode": config.notification_mode,
            "primary_email": config.primary_email,
            "backup_enabled": config.backup_enabled,
            "backup_email": config.backup_email,
            "jev_model": config.jev_model,
            "speechmatics_model": config.speechmatics_model,
            **{field: getattr(config, field) for field in SMILE_FIELDS},
            "smile_timezone": SMILE_TIMEZONE,
            "smile_collector_id": str(config.smile_collector_id) if config.smile_collector_id else None,
            "smile_legacy_active": bool(config.smile_legacy_sources),
            "options": {
                "jev_models": JevVersion.values,
                "speechmatics_models": SpeechmaticsModel.values,
                "smile_formats": dict(SmileFormat.choices),
                "smile_timezones": [SMILE_TIMEZONE],
                "smile_collectors": collector_options(),
                "smile_boxes": registrable_boxes(),
            },
            "timezone": config.timezone,
            "updated_at": config.updated_at.isoformat().replace("+00:00", "Z") if config.updated_at else None,
        }

    def update_config(self, actor, data):
        # Criterio: Solo los administradores pueden modificar la configuración.
        if not (actor.is_authenticated and actor.is_active and getattr(actor, "is_admin", False)):
            raise ServiceError("AUTH_FORBIDDEN", "No tienes permisos para modificar la configuración operativa.", 403)

        with transaction.atomic():
            if isinstance(data, dict) and set(data).intersection(SMILE_FIELDS):
                from backend.apps.capture.pairing import registration_lock
                registration_lock()
            config = OperationalConfiguration.load()
            config = OperationalConfiguration.objects.select_for_update().get(pk=config.pk)
            serializer = OperationalConfigSerializer(instance=config, data=data)
            if not serializer.is_valid():
                raise ServiceError(
                    "VALIDATION_ERROR", "Datos de entrada inválidos", 400,
                    details={"fields": serializer.errors},
                )
            before_duration = config.audio_chunk_duration
            before_mode = config.audio_chunk_mode
            data = serializer.validated_data
            if any(field in data and data[field] != getattr(config, field) for field in (
                "smile_collector_id", "smile_source", "smile_url", "smile_format", "smile_boxes",
            )):
                config.smile_revision += 1
            enabled_days = data.get("enabled_days")
            open_time = data.get("open_time")
            close_time = data.get("close_time")

            if open_time is not None or close_time is not None:
                try:
                    t_open = time.fromisoformat(data.get("open_time", config.open_time))
                    t_close = time.fromisoformat(data.get("close_time", config.close_time))
                    if t_open >= t_close:
                        raise ValueError()
                except ValueError:
                    raise ServiceError("VALIDATION_ERROR", "Horario de apertura y cierre inválido o invertido.", 400)

            if enabled_days is not None:
                config.enabled_days = sorted(list(set(enabled_days)))
            if open_time is not None:
                config.open_time = open_time
            if close_time is not None:
                config.close_time = close_time
            for field in ("notification_mode", "primary_email", "backup_enabled", "backup_email",
                          "audio_chunk_duration", "audio_chunk_mode", "jev_model", "speechmatics_model", *SMILE_FIELDS):
                if field in data:
                    setattr(config, field, data[field])
            if "smile_collector_id" in data:
                config.smile_legacy_sources = {}
            config.save()
            if (before_duration, before_mode) != (config.audio_chunk_duration, config.audio_chunk_mode):
                AudioChunkConfigurationChange.objects.create(
                    actor_id=str(actor.pk),
                    before_duration=before_duration, after_duration=config.audio_chunk_duration,
                    before_mode=before_mode, after_mode=config.audio_chunk_mode,
                )

        return self._serialize_config(config)

    def validate_current_operation(self, check_time: datetime | None = None) -> dict:
        """Valida centralmente si el sistema está operando dentro del horario habilitado."""
        current_dt = (check_time or datetime.now(SANTIAGO_TZ)).astimezone(SANTIAGO_TZ)
        config = OperationalConfiguration.load()

        # Si no hay correos configurados o datos básicos, se considera no autorizado
        if not config.primary_email and not config.open_time:
            return {
                "authorized": False,
                "reason": "La captura y el procesamiento no están autorizados: no existe configuración operativa vigente.",
            }

        weekday = current_dt.weekday()  # 0 = Lunes, 6 = Domingo
        current_t = current_dt.time().replace(second=0, microsecond=0)

        try:
            t_open = time.fromisoformat(config.open_time)
            t_close = time.fromisoformat(config.close_time)
        except ValueError:
            return {"authorized": False, "reason": "Configuración horaria inválida."}

        is_day_ok = weekday in config.enabled_days
        is_time_ok = t_open <= current_t < t_close

        if not (is_day_ok and is_time_ok):
            return {
                "authorized": False,
                "reason": "La captura y el procesamiento no están autorizados fuera del horario configurado.",
            }

        return {
            "authorized": True,
            "reason": "Operación autorizada dentro del horario clínico.",
            "primary_email": config.primary_email,
            "backup_email": config.backup_email,
        }

    def authorize_box_capture(self, box: str | int, check_time: datetime | None = None) -> BoxCaptureAuthorization:
        """SCRUM-70: Evalúa autorización de captura para un box combinando agenda y horario clínico."""
        if self._durable_agenda:
            from backend.apps.agenda.persistence import refresh
            refresh(self._capture_auth.agenda)
        check_time = self._capture_auth._normalize_when(check_time)
        authorization = self._capture_auth.evaluate_box(box, check_time)
        self._capture_sessions.apply_authorization(authorization, now=check_time)
        return authorization

    def authorize_box_transition(self, box: str | int, check_time: datetime | None = None) -> BoxCaptureAuthorization | None:
        """SCRUM-70: Devuelve la autorización solo cuando ocurre una transición de estado."""
        if self._durable_agenda:
            from backend.apps.agenda.persistence import refresh
            refresh(self._capture_auth.agenda)
        check_time = self._capture_auth._normalize_when(check_time)
        transition = self._capture_auth.evaluate_transition(box, check_time)
        authorization = transition or self._capture_auth.evaluate_box(box, check_time)
        self._capture_sessions.apply_authorization(authorization, now=check_time)
        return transition
