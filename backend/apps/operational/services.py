from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo
from django.db import transaction
from backend.common.errors import ServiceError
from backend.apps.capture.services import CaptureSessionService
from .capture_authorization import BoxCaptureAuthorization, CaptureAuthorizationService
from .models import OperationalConfiguration

SANTIAGO_TZ = ZoneInfo("America/Santiago")


class OperationalService:
    def __init__(self, agenda_service=None):
        self._durable_agenda = agenda_service is None
        self._capture_auth = CaptureAuthorizationService(agenda_service=agenda_service)
        self._capture_sessions = CaptureSessionService(self._capture_auth)

    def get_config(self):
        config = OperationalConfiguration.load()
        return {
            "enabled_days": config.enabled_days,
            "open_time": config.open_time,
            "close_time": config.close_time,
            "primary_email": config.primary_email,
            "backup_email": config.backup_email,
            "timezone": config.timezone,
            "updated_at": config.updated_at.isoformat().replace("+00:00", "Z") if config.updated_at else None,
        }

    def update_config(self, actor, data):
        # Criterio: Solo los administradores pueden modificar la configuración.
        if not (actor.is_authenticated and actor.is_active and getattr(actor, "is_admin", False)):
            raise ServiceError("AUTH_FORBIDDEN", "No tienes permisos para modificar la configuración operativa.", 403)

        enabled_days = data.get("enabled_days")
        open_time = data.get("open_time")
        close_time = data.get("close_time")
        primary_email = data.get("primary_email")
        backup_email = data.get("backup_email")

        # Validaciones básicas
        if enabled_days is not None:
            if not isinstance(enabled_days, list) or any(not isinstance(d, int) or d < 0 or d > 6 for d in enabled_days):
                raise ServiceError("VALIDATION_ERROR", "Días habilitados inválidos (deben ser enteros entre 0 y 6).", 400)

        if open_time is not None or close_time is not None:
            try:
                t_open = time.fromisoformat(open_time or "00:00")
                t_close = time.fromisoformat(close_time or "23:59")
                if t_open >= t_close:
                    raise ValueError()
            except ValueError:
                raise ServiceError("VALIDATION_ERROR", "Horario de apertura y cierre inválido o invertido.", 400)

        with transaction.atomic():
            config = OperationalConfiguration.load()
            if enabled_days is not None:
                config.enabled_days = sorted(list(set(enabled_days)))
            if open_time is not None:
                config.open_time = open_time
            if close_time is not None:
                config.close_time = close_time
            if primary_email is not None:
                config.primary_email = primary_email.strip().lower()
            if backup_email is not None:
                config.backup_email = backup_email.strip().lower()
            config.save()

        return self.get_config()

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
