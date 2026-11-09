"""SCRUM-70: Integración de agenda (SCRUM-61) y horario clínico (SCRUM-67) para autorizar captura."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from threading import Lock
from backend.common.boxes import is_box, known_boxes
from typing import Callable
from zoneinfo import ZoneInfo

from backend.apps.agenda.services import (
    NON_BLOCKING,
    AgendaError,
    AgendaNotLoaded,
    AgendaService,
    _box,
    _local_datetime,
)
from backend.common.audit import AuditWriter

from .models import OperationalConfiguration

SANTIAGO_TZ = ZoneInfo("America/Santiago")
UTC = timezone.utc

ORIGIN_AGENDA = "agenda"
ORIGIN_CLINICAL_SCHEDULE = "horario_clinico"
ORIGIN_NONE = "ninguno"


@dataclass(frozen=True)
class BoxCaptureAuthorization:
    """Contrato de salida hacia SCRUM-71 con estado de autorización por box."""
    box: str
    authorized: bool
    inicio: datetime | None
    termino: datetime | None
    origen: str

    @property
    def autorizado(self) -> bool:
        return self.authorized

    @property
    def estado_autorizacion(self) -> str:
        return "AUTORIZADO" if self.authorized else "DENEGADO"

    def to_dict(self) -> dict:
        return {
            "box": self.box,
            "authorized": self.authorized,
            "autorizado": self.authorized,
            "estado_autorizacion": self.estado_autorizacion,
            "inicio": self.inicio.isoformat() if self.inicio else None,
            "termino": self.termino.isoformat() if self.termino else None,
            "origen": self.origen,
        }


def _load_clinical_config() -> OperationalConfiguration | None:
    """Consulta el horario existente sin crear una configuración que autorice captura."""
    return OperationalConfiguration.objects.filter(pk=1).first()


def _resolve_clinical_window(config, current_dt: datetime) -> tuple[datetime, datetime] | None:
    """Calcula la ventana [apertura, cierre) del horario clínico para la fecha local de current_dt."""
    if config is None:
        return None
    enabled_days = getattr(config, "enabled_days", None)
    open_str = getattr(config, "open_time", "")
    close_str = getattr(config, "close_time", "")

    if not isinstance(enabled_days, list) or not open_str or not close_str:
        return None
    if current_dt.weekday() not in enabled_days:
        return None

    try:
        t_open = time.fromisoformat(open_str)
        t_close = time.fromisoformat(close_str)
    except (ValueError, TypeError):
        return None

    if t_open >= t_close:
        return None

    day = current_dt.date()
    start_dt = datetime.combine(day, t_open, tzinfo=SANTIAGO_TZ)
    end_dt = datetime.combine(day, t_close, tzinfo=SANTIAGO_TZ)

    if not (start_dt <= current_dt < end_dt):
        return None

    return start_dt, end_dt


def _find_active_appointment(agenda: AgendaService, box_name: str, current_dt: datetime):
    """Obtiene la cita vigente del box en memoria sin usar datos de pacientes."""
    # Verifica primero ocupación mediante el contrato público de AgendaService (valida box y carga)
    if not agenda.is_busy(box_name, current_dt):
        return None

    instant_utc = current_dt.astimezone(UTC)
    by_box = getattr(agenda, "_by_box", {})
    for item in by_box.get(box_name, ()):
        if (
            item.estatus not in NON_BLOCKING
            and item.inicio.astimezone(UTC) <= instant_utc < item.termino.astimezone(UTC)
        ):
            return item
    return None


class CaptureAuthorizationService:
    """Combina el horario clínico con la ocupación en memoria de la agenda por box."""

    def __init__(
        self,
        agenda_service: AgendaService | None = None,
        config_loader: Callable[[], OperationalConfiguration | None] | None = None,
    ):
        # Si se reinicia el proceso, una instancia nueva de AgendaService inicia vacía (no disponible)
        self.agenda = agenda_service if agenda_service is not None else AgendaService()
        self.config_loader = config_loader if config_loader is not None else _load_clinical_config
        self._last_states: dict[str, bool] = {}
        self._logged_conditions: dict[str, str] = {}
        self._lock = Lock()

    def _normalize_box(self, box: str | int) -> str:
        box_name = _box(box)
        if not is_box(box_name):
            raise AgendaError("box_fuera_de_alcance")
        return box_name

    def _normalize_when(self, when: datetime | None) -> datetime:
        if when is None:
            return datetime.now(SANTIAGO_TZ)
        return _local_datetime(when)

    def _record_audit_once(self, box_name: str, condition_key: str, action: str, outcome: str, error_code: str | None = None):
        with self._lock:
            if self._logged_conditions.get(box_name) == condition_key:
                return
            self._logged_conditions[box_name] = condition_key
        AuditWriter.record(action, outcome, error_code=error_code)

    def _clear_audit_condition(self, box_name: str, condition_key: str | None = None):
        with self._lock:
            if condition_key is None or self._logged_conditions.get(box_name) == condition_key:
                self._logged_conditions.pop(box_name, None)

    def evaluate_box(self, box: str | int, when: datetime | None = None) -> BoxCaptureAuthorization:
        """Determina si el box está autorizado para capturar en el instante indicado."""
        box_name = self._normalize_box(box)
        current_dt = self._normalize_when(when)
        from backend.apps.agenda.models import SmileRoom
        if SmileRoom.objects.filter(box=box_name, available=False).exists():
            return BoxCaptureAuthorization(box_name, False, None, None, ORIGIN_NONE)

        try:
            config = self.config_loader()
        except Exception:
            self._record_audit_once(
                box_name,
                "config_error",
                "capture.authorization",
                "failure",
                error_code="CLINICAL_SCHEDULE_UNAVAILABLE",
            )
            return BoxCaptureAuthorization(
                box=box_name,
                authorized=False,
                inicio=None,
                termino=None,
                origen=ORIGIN_NONE,
            )

        # Una lectura exitosa termina el incidente, incluso fuera de horario.
        # Conserva la deduplicación de los registros de respaldo de la agenda.
        self._clear_audit_condition(box_name, "config_error")
        clinical_window = _resolve_clinical_window(config, current_dt)
        if clinical_window is None:
            return BoxCaptureAuthorization(
                box=box_name,
                authorized=False,
                inicio=None,
                termino=None,
                origen=ORIGIN_CLINICAL_SCHEDULE,
            )

        sched_start, sched_end = clinical_window

        try:
            appointment = _find_active_appointment(self.agenda, box_name, current_dt)
        except AgendaNotLoaded:
            # Respaldo automático con el horario clínico cuando la agenda del box no está cargada
            self._record_audit_once(
                box_name,
                f"fallback_not_loaded:{sched_start.date().isoformat()}",
                "capture.authorization.fallback",
                "success",
                error_code="AGENDA_NOT_AVAILABLE",
            )
            return BoxCaptureAuthorization(
                box=box_name,
                authorized=True,
                inicio=sched_start,
                termino=sched_end,
                origen=ORIGIN_CLINICAL_SCHEDULE,
            )
        except Exception:
            # Fallo inesperado al consultar la agenda: registrar fallo y usar horario clínico de respaldo
            self._record_audit_once(
                box_name,
                f"fallback_error:{sched_start.date().isoformat()}",
                "capture.authorization",
                "failure",
                error_code="AGENDA_QUERY_FAILED",
            )
            return BoxCaptureAuthorization(
                box=box_name,
                authorized=True,
                inicio=sched_start,
                termino=sched_end,
                origen=ORIGIN_CLINICAL_SCHEDULE,
            )

        self._clear_audit_condition(box_name)

        if appointment is None:
            return BoxCaptureAuthorization(
                box=box_name,
                authorized=False,
                inicio=None,
                termino=None,
                origen=ORIGIN_AGENDA,
            )

        effective_start = max(appointment.inicio.astimezone(SANTIAGO_TZ), sched_start)
        effective_end = min(appointment.termino.astimezone(SANTIAGO_TZ), sched_end)

        if effective_start >= effective_end:
            return BoxCaptureAuthorization(
                box=box_name,
                authorized=False,
                inicio=None,
                termino=None,
                origen=ORIGIN_AGENDA,
            )

        return BoxCaptureAuthorization(
            box=box_name,
            authorized=True,
            inicio=effective_start,
            termino=effective_end,
            origen=ORIGIN_AGENDA,
        )

    def evaluate_transition(self, box: str | int, when: datetime | None = None) -> BoxCaptureAuthorization | None:
        """Informa el estado inicial y cada cambio entre autorizado y denegado."""
        current = self.evaluate_box(box, when)
        with self._lock:
            previous = self._last_states.get(current.box)
            if previous == current.authorized:
                return None
            self._last_states[current.box] = current.authorized
        AuditWriter.record(
            "capture.authorization.transition",
            "success" if current.authorized else "skipped",
        )
        return current

    def evaluate_all_boxes(self, when: datetime | None = None) -> tuple[BoxCaptureAuthorization, ...]:
        """Evalúa las salas conocidas del registro y de la agenda."""
        return tuple(self.evaluate_box(box, when) for box in known_boxes())

    def evaluate_all_transitions(self, when: datetime | None = None) -> tuple[BoxCaptureAuthorization, ...]:
        """Devuelve únicamente los boxes que cambiaron su estado de autorización."""
        transitions = []
        for box in known_boxes():
            change = self.evaluate_transition(box, when)
            if change is not None:
                transitions.append(change)
        return tuple(transitions)
