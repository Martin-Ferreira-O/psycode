"""Ciclo de captura y bandeja de órdenes durable; sin I/O del agente dentro de SQL."""
from datetime import datetime, timedelta
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from backend.common.audit import AuditWriter
from .domain import CaptureError, Command, Session, TECHNICAL_ERRORS
from .models import (
    OPEN_STATES, AcceptedSequence, AgentCommand, CaptureEvent, CaptureSession,
    CommandKind, FragmentJob, SessionState,
)


def _instant(value=None):
    value = timezone.now() if value is None else value
    if not isinstance(value, datetime) or timezone.is_naive(value):
        raise CaptureError("INVALID_TIMESTAMP")
    return value


def _box(value):
    if type(value) is int or (isinstance(value, str) and value.isdigit()):
        value = f"box-{value}"
    if not isinstance(value, str) or value not in {f"box-{n}" for n in range(3, 8)}:
        raise CaptureError("INVALID_BOX")
    return value


def _uuid(value):
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise CaptureError("INVALID_IDENTIFIER") from None


def _snapshot(session):
    return Session(**{name: getattr(session, name) for name in Session.__dataclass_fields__})


def _event(session, action, now, *, command=None, sequence=None, error_code=""):
    event = CaptureEvent.objects.create(
        session=session, timestamp=now, action=f"capture.{action}", state=session.state,
        command_id=command.command_id if command else None, sequence=sequence, error_code=error_code,
    )
    payload = {
        "event_id": str(event.event_id), "timestamp": now, "action": event.action,
        "outcome": "failure" if error_code else "success", "sesion_id": str(session.pk),
        "box": session.box, "state": session.state, "sequence": sequence,
        "command_id": str(event.command_id) if event.command_id else None, "error_code": error_code or None,
    }
    transaction.on_commit(lambda: AuditWriter.emit(payload), robust=True)


class CaptureSessionService:
    def __init__(self, authorization_service=None, *, start_timeout=None,
                 heartbeat_timeout=None, finalization_timeout=None, reception_grace=None):
        from django.conf import settings
        start_timeout = start_timeout if start_timeout is not None else timedelta(seconds=settings.CAPTURE_START_TIMEOUT_SECONDS)
        heartbeat_timeout = heartbeat_timeout if heartbeat_timeout is not None else timedelta(seconds=settings.CAPTURE_INACTIVITY_TIMEOUT_SECONDS)
        finalization_timeout = finalization_timeout if finalization_timeout is not None else timedelta(seconds=settings.CAPTURE_FINALIZATION_TIMEOUT_SECONDS)
        reception_grace = reception_grace if reception_grace is not None else timedelta(seconds=settings.CAPTURE_RECEPTION_GRACE_SECONDS)
        if any(value <= timedelta(0) for value in (start_timeout, heartbeat_timeout, finalization_timeout, reception_grace)):
            raise ValueError("Los tiempos de espera deben ser positivos")
        self.authorization_service = authorization_service
        self.start_timeout = start_timeout
        self.heartbeat_timeout = heartbeat_timeout
        self.finalization_timeout = finalization_timeout
        self.reception_grace = reception_grace

    def reconcile_box(self, box, *, now=None):
        """Evaluar SCRUM-70 en cada tick, no solo sus transiciones en memoria."""
        if self.authorization_service is None:
            raise ValueError("Se requiere el servicio de autorización")
        now = _instant(now)
        authorization = self.authorization_service.evaluate_box(_box(box), now)
        return self.apply_authorization(authorization, now=now)

    def apply_authorization(self, authorization, *, now=None):
        now, box = _instant(now), _box(authorization.box)
        if type(authorization.authorized) is not bool:
            raise CaptureError("INVALID_AUTHORIZATION")
        if authorization.authorized:
            start, end = _instant(authorization.inicio), _instant(authorization.termino)
            if authorization.inicio is None or authorization.termino is None or not start <= now < end:
                raise CaptureError("INVALID_AUTHORIZATION_WINDOW")
            if authorization.origen not in {"agenda", "horario_clinico"}:
                raise CaptureError("INVALID_AUTHORIZATION_ORIGIN")
        # IMMEDIATE serializa escritores en SQLite; select_for_update protege
        # filas existentes en motores con bloqueos de fila. Las restricciones
        # únicas también cubren la carrera al insertar la primera sesión.
        with transaction.atomic():
            # Una revocación o cambio de contexto termina la autorización
            # incluso si su sesión ya falló. El marcador sobrevive reinicios
            # y permite otra sesión en la misma ventana sin repetir ticks.
            ending = CaptureSession.objects.select_for_update().filter(box=box, authorization_ended_at=None)
            if authorization.authorized:
                ending = ending.exclude(origin=authorization.origen, scheduled_start=start, scheduled_end=end)
            for previous in ending:
                previous.authorization_ended_at = now
                previous.save(update_fields=["authorization_ended_at"])
                _event(previous, "authorization.ended", now)
            current = CaptureSession.objects.select_for_update().filter(
                box=box, state__in=OPEN_STATES, actual_end__isnull=True,
            ).first()
            if current:
                if (not authorization.authorized or now >= current.scheduled_end
                        or (authorization.authorized and (
                            current.scheduled_start != start or current.scheduled_end != end
                            or current.origin != authorization.origen))):
                    self._stop(current, now)
                self._expire(current, now)
                return _snapshot(current)
            if not authorization.authorized:
                return None
            # Una detención de una sesión fallida bloquea nuevos inicios
            # hasta que el agente confirme que dejó de capturar.
            if AgentCommand.objects.filter(session__box=box, session__actual_end__isnull=True,
                                           kind=CommandKind.STOP).exclude(succeeded=True).exists():
                return None
            previous = CaptureSession.objects.filter(
                box=box, origin=authorization.origen, scheduled_start=start, scheduled_end=end,
                authorization_ended_at=None,
            ).first()
            if previous:
                return _snapshot(previous)
            try:
                with transaction.atomic():
                    session = CaptureSession.objects.create(
                        box=box, state=SessionState.STARTED, origin=authorization.origen,
                        scheduled_start=start, scheduled_end=end, authorized_at=now, last_seen_at=now,
                    )
            except IntegrityError:
                # Solo recuperar la carrera de inserción. Los errores en
                # órdenes o bitácora deben revertir toda la operación.
                existing = CaptureSession.objects.filter(box=box, state__in=OPEN_STATES, actual_end__isnull=True).first()
                if existing is None:
                    existing = CaptureSession.objects.filter(
                        box=box, origin=authorization.origen, scheduled_start=start, scheduled_end=end,
                        authorization_ended_at=None,
                    ).first()
                if existing is None:
                    raise
                return _snapshot(existing)
            _event(session, "session.created", now)
            self._command(session, CommandKind.START, now)
            return _snapshot(session)

    def _command(self, session, kind, now):
        command, created = AgentCommand.objects.get_or_create(session=session, kind=kind, defaults={"created_at": now})
        if created:
            _event(session, "command.created", now, command=command)
        return command

    def _stop(self, session, now):
        if session.state not in (SessionState.STARTED, SessionState.ACTIVE):
            return
        session.state = SessionState.STOPPING
        session.stop_requested_at = now
        session.save(update_fields=["state", "stop_requested_at"])
        AgentCommand.objects.filter(session=session, kind=CommandKind.START, acknowledged_at=None).update(cancelled_at=now)
        self._command(session, CommandKind.STOP, now)
        _event(session, "session.stopping", now)

    def _fail(self, session, code, now):
        if session.state not in OPEN_STATES:
            return
        self._stop(session, now)
        session.state, session.error_code, session.closed_at = SessionState.FAILED, code, now
        session.diagnostic_code = ""
        session.save(update_fields=["state", "error_code", "closed_at", "diagnostic_code"])
        _event(session, "session.failed", now, error_code=code)

    def _complete(self, session, now):
        if (session.state == SessionState.STOPPING and session.actual_end is not None
                and session.final_sequence is not None and session.next_sequence == session.final_sequence + 1):
            session.state, session.closed_at = SessionState.COMPLETED, now
            session.diagnostic_code = ""
            session.save(update_fields=["state", "closed_at", "diagnostic_code"])
            _event(session, "session.completed", now)

    def _capture_limit(self, session):
        return min(value for value in (session.scheduled_end, session.authorization_ended_at,
                                       session.stop_requested_at, session.actual_end) if value is not None)

    def _reception_deadline(self, session):
        deadline = self._capture_limit(session) + self.reception_grace
        return max(deadline, session.reception_extended_until) if session.reception_extended_until else deadline

    def _diagnose(self, session, code, now):
        if session.diagnostic_code == code:
            return
        session.diagnostic_code = code
        session.save(update_fields=["diagnostic_code"])
        _event(session, "session.diagnostic", now, error_code=code)

    def _expire(self, session, now):
        if session.state in (SessionState.STARTED, SessionState.ACTIVE) and now >= session.scheduled_end:
            self._stop(session, now)
        if session.state == SessionState.STOPPING or (session.state == SessionState.FAILED and session.actual_end is not None):
            if (session.actual_end is not None and session.final_sequence is not None
                    and session.next_sequence == session.final_sequence + 1):
                return
            if now >= self._reception_deadline(session):
                if session.reception_intervention_at is None:
                    session.reception_intervention_at = now
                    session.save(update_fields=["reception_intervention_at"])
                self._diagnose(session, "RECEPTION_INTERVENTION_REQUIRED", now)
            elif session.actual_end is None and now >= session.stop_requested_at + self.finalization_timeout:
                self._diagnose(session, "STOP_CONFIRMATION_PENDING", now)
        elif session.state == SessionState.STARTED and now >= session.authorized_at + self.start_timeout:
            self._diagnose(session, "START_CONFIRMATION_PENDING", now)
        elif session.state == SessionState.ACTIVE and now >= session.last_seen_at + self.heartbeat_timeout:
            self._diagnose(session, "CONTROL_DISCONNECTED", now)

    def recover(self, *, now=None):
        """Una pasada recuperable tras reinicio; ejecutar periódicamente."""
        now, changed = _instant(now), 0
        ids = list(CaptureSession.objects.filter(state__in=OPEN_STATES).values_list("pk", flat=True))
        for session_id in ids:
            with transaction.atomic():
                session = CaptureSession.objects.select_for_update().get(pk=session_id)
                previous = session.state, session.diagnostic_code, session.reception_intervention_at
                self._expire(session, now)
                changed += previous != (session.state, session.diagnostic_code, session.reception_intervention_at)
        return changed

    def _load(self, box, session_id):
        session = CaptureSession.objects.select_for_update().filter(pk=_uuid(session_id), box=_box(box)).first()
        if session is None:
            raise CaptureError("SESSION_NOT_FOUND")
        return session

    def commands(self, box, *, now=None):
        now, box = _instant(now), _box(box)
        # Recuperación y entrega comparten la transacción: no se publica un
        # inicio vencido, incluso si el programador externo dejó de ejecutar ticks.
        with transaction.atomic():
            sessions = list(CaptureSession.objects.select_for_update().filter(box=box, state__in=OPEN_STATES))
            for session in sessions:
                self._expire(session, now)
            pending = AgentCommand.objects.filter(session__box=box, cancelled_at=None).exclude(succeeded=True)
            pending = pending.exclude(kind=CommandKind.STOP, session__actual_end__isnull=False)
            # Fallos de inicio no se reejecutan; las detenciones sí se reintentan.
            pending = pending.exclude(kind=CommandKind.START, acknowledged_at__isnull=False)
            commands = list(pending.select_for_update().select_related("session").order_by("created_at", "command_id"))
            stops = [item for item in commands if item.kind == CommandKind.STOP]
            if stops:
                commands = stops
            result = []
            for item in commands:
                item.delivered_at, item.delivery_count = now, item.delivery_count + 1
                item.save(update_fields=["delivered_at", "delivery_count"])
                _event(item.session, "command.delivered", now, command=item)
                result.append(Command(item.command_id, item.session_id, box, item.kind,
                                      item.session.scheduled_start, min(item.session.scheduled_end, item.session.stop_requested_at)
                                      if item.kind == CommandKind.STOP and item.session.stop_requested_at else item.session.scheduled_end))
            return tuple(result)

    def acknowledge(self, box, command_id, *, success=True, last_sequence=None, error_code="",
                    occurred_at=None, now=None):
        now = _instant(now)
        occurred = None if occurred_at is None else _instant(occurred_at)
        if type(success) is not bool or error_code not in TECHNICAL_ERRORS | {""} or (success and error_code):
            raise CaptureError("INVALID_CONFIRMATION")
        reference = AgentCommand.objects.filter(pk=_uuid(command_id), session__box=_box(box)).first()
        if reference is None:
            raise CaptureError("COMMAND_NOT_FOUND")
        self._recover_one(box, reference.session_id, now)
        with transaction.atomic():
            # Siempre bloquear sesión antes de orden, igual que los demás métodos.
            session = self._load(box, reference.session_id)
            command = AgentCommand.objects.select_for_update().get(pk=reference.pk)
            if command.delivered_at is None:
                raise CaptureError("COMMAND_NOT_DELIVERED")
            if command.kind == CommandKind.STOP and success:
                if type(last_sequence) is not int or not -1 <= last_sequence <= 9223372036854775806:
                    raise CaptureError("INVALID_FINAL_SEQUENCE")
            elif last_sequence is not None:
                raise CaptureError("INVALID_FINAL_SEQUENCE")
            code = error_code or ("AGENT_START_FAILED" if command.kind == CommandKind.START else "AGENT_STOP_FAILED")
            code = "" if success else code
            if command.acknowledged_at is not None:
                identical = (command.succeeded == success and command.last_sequence == last_sequence
                             and command.error_code == code and (occurred is None or command.occurred_at == occurred))
                if identical:
                    return _snapshot(session)
                # Una detención fallida puede confirmarse tras reentregarla.
                if not (command.kind == CommandKind.STOP and command.succeeded is False and success):
                    raise CaptureError("CONFIRMATION_CONFLICT")
            occurred = occurred or now
            if not session.authorized_at <= occurred <= now:
                raise CaptureError("INVALID_TIMESTAMP")
            if (success and command.kind == CommandKind.STOP and occurred < command.created_at
                    and occurred < self._capture_limit(session)):
                raise CaptureError("INVALID_TIMESTAMP")
            if success and command.kind == CommandKind.START:
                if occurred >= session.scheduled_end or (session.actual_end and occurred > session.actual_end):
                    raise CaptureError("INVALID_TIMESTAMP")
                session.actual_start = occurred
                if session.state == SessionState.STARTED:
                    if now >= session.scheduled_end:
                        self._stop(session, now)
                    else:
                        session.state = SessionState.ACTIVE
            elif success:
                latest = session.sequences.order_by("-number").first()
                if (last_sequence < session.next_sequence - 1
                        or (session.actual_start and occurred < session.actual_start)
                        or (latest and occurred < latest.captured_at)):
                    raise CaptureError("INVALID_FINAL_SEQUENCE")
                if session.actual_end is not None and session.actual_end != occurred:
                    raise CaptureError("CONFIRMATION_CONFLICT")
                if session.final_sequence is not None and session.final_sequence != last_sequence:
                    raise CaptureError("CONFIRMATION_CONFLICT")
                session.actual_end, session.final_sequence = occurred, last_sequence
            command.acknowledged_at, command.succeeded = now, success
            command.occurred_at, command.last_sequence, command.error_code = occurred, last_sequence, code
            command.save(update_fields=["acknowledged_at", "succeeded", "occurred_at", "last_sequence", "error_code"])
            session.last_seen_at = max(session.last_seen_at, now)
            if (session.diagnostic_code == "CONTROL_DISCONNECTED"
                    or command.kind == CommandKind.START and session.diagnostic_code == "START_CONFIRMATION_PENDING"
                    or command.kind == CommandKind.STOP and session.diagnostic_code == "STOP_CONFIRMATION_PENDING"):
                session.diagnostic_code = ""
            session.save(update_fields=["state", "actual_start", "actual_end", "final_sequence", "last_seen_at", "diagnostic_code"])
            _event(session, "command.acknowledged", now, command=command, error_code=code)
            if not success:
                self._fail(session, code, now)
            self._complete(session, now)
            return _snapshot(session)

    def accept_sequence(self, box, session_id, number, captured_at, *, now=None):
        if captured_at is None:
            raise CaptureError("INVALID_TIMESTAMP")
        now, captured_at = _instant(now), _instant(captured_at)
        if type(number) is not int or not 0 <= number <= 9223372036854775806:
            raise CaptureError("INVALID_SEQUENCE")
        self._recover_one(box, session_id, now)
        with transaction.atomic():
            session = self._load(box, session_id)
            return self._accept_sequence(session, number, captured_at, now)

    def _accept_sequence(self, session, number, captured_at, now):
        """Registra bajo el bloqueo de sesión y la transacción del llamador."""
        existing = AcceptedSequence.objects.filter(session=session, number=number).first()
        if existing:
            if existing.captured_at != captured_at:
                raise CaptureError("SEQUENCE_CONFLICT")
            return False
        receiving = session.state in (SessionState.ACTIVE, SessionState.STOPPING) or (
            session.state == SessionState.FAILED and session.actual_end is not None)
        if not receiving or session.actual_start is None:
            raise CaptureError("SESSION_NOT_ACCEPTING_SEQUENCES")
        if session.state in (SessionState.STOPPING, SessionState.FAILED) and now >= self._reception_deadline(session):
            raise CaptureError("RECEPTION_INTERVENTION_REQUIRED")
        if number != session.next_sequence or (session.final_sequence is not None and number > session.final_sequence):
            raise CaptureError("SEQUENCE_OUT_OF_ORDER")
        upper = min(value for value in (self._capture_limit(session), now)
                    if value is not None)
        if not session.actual_start <= captured_at <= upper:
            raise CaptureError("SEQUENCE_OUTSIDE_CAPTURE_WINDOW")
        previous = AcceptedSequence.objects.filter(session=session, number=number - 1).first()
        if previous and captured_at < previous.captured_at:
            raise CaptureError("INVALID_TIMESTAMP")
        AcceptedSequence.objects.create(session=session, number=number, captured_at=captured_at, accepted_at=now)
        session.next_sequence += 1
        session.last_seen_at = max(session.last_seen_at, now)
        if session.diagnostic_code == "CONTROL_DISCONNECTED":
            session.diagnostic_code = ""
        session.save(update_fields=["next_sequence", "last_seen_at", "diagnostic_code"])
        _event(session, "sequence.accepted", now, sequence=number)
        self._complete(session, now)
        return True

    def _recover_one(self, box, session_id, now):
        # Confirmaciones o secuencias tardías no reviven una sesión vencida.
        # La recuperación se confirma aunque la operación posterior se rechace.
        with transaction.atomic():
            self._expire(self._load(box, session_id), now)

    def heartbeat(self, box, session_id, *, now=None):
        now = _instant(now)
        with transaction.atomic():
            session = self._load(box, session_id)
            self._expire(session, now)
            if session.state in OPEN_STATES:
                session.last_seen_at = max(session.last_seen_at, now)
                if session.diagnostic_code == "CONTROL_DISCONNECTED":
                    session.diagnostic_code = ""
                session.save(update_fields=["last_seen_at", "diagnostic_code"])
            return _snapshot(session)

    def resume_reception(self, box, session_id, *, now=None, until=None):
        """Intervención explícita del operador; nunca modifica autorización ni captura."""
        now = _instant(now)
        until = _instant(until) if until is not None else now + self.reception_grace
        if until <= now:
            raise CaptureError("INVALID_TIMESTAMP")
        with transaction.atomic():
            session = self._load(box, session_id)
            self._expire(session, now)
            if session.state == SessionState.FAILED and session.error_code in {
                "AGENT_UNAVAILABLE", "SESSION_ABANDONED", "FINAL_SEQUENCE_TIMEOUT",
            }:
                # Recuperación explícita de cierres por red de versiones anteriores.
                # No convertir fallos reales de OBS/captura en sesiones recuperables.
                if session.actual_end is None and CaptureSession.objects.filter(
                    box=session.box, state__in=OPEN_STATES, actual_end__isnull=True,
                ).exclude(pk=session.pk).exists():
                    raise CaptureError("CAPTURE_STATE_CONFLICT")
                session.state = SessionState.STOPPING
                session.closed_at = None
                session.error_code = ""
                session.stop_requested_at = session.stop_requested_at or min(now, session.scheduled_end)
                session.save(update_fields=["state", "closed_at", "error_code", "stop_requested_at"])
            if session.state != SessionState.STOPPING and not (
                session.state == SessionState.FAILED and session.actual_end is not None
            ):
                raise CaptureError("SESSION_NOT_ACCEPTING_SEQUENCES")
            session.reception_extended_until = max(until, self._reception_deadline(session))
            session.reception_intervention_at = None
            session.diagnostic_code = ""
            session.save(update_fields=["reception_extended_until", "reception_intervention_at", "diagnostic_code"])
            _event(session, "reception.resumed", now)
            return _snapshot(session)

    def confirm_capture_ended(self, box, session_id, *, ended_at, last_sequence=None, reason_code, now=None):
        """Evidencia física separada del ACK: no inventa una secuencia desconocida."""
        now, ended_at = _instant(now), _instant(ended_at)
        if reason_code not in {"AUTHORIZATION_ENDED", "AGENT_STOPPED", "AGENT_INTERRUPTED", "RECOVERY_STOPPED", "DISK_LOW", "SHUTDOWN"}:
            raise CaptureError("INVALID_TECHNICAL_ERROR")
        if last_sequence is not None and (type(last_sequence) is not int or not -1 <= last_sequence <= 9223372036854775806):
            raise CaptureError("INVALID_FINAL_SEQUENCE")
        with transaction.atomic():
            session = self._load(box, session_id)
            if (not session.authorized_at <= ended_at <= now
                    or (session.actual_start and ended_at < session.actual_start)):
                raise CaptureError("INVALID_TIMESTAMP")
            latest = session.sequences.order_by("-number").first()
            if latest and ended_at < latest.captured_at:
                raise CaptureError("INVALID_TIMESTAMP")
            if (session.actual_end is not None and session.actual_end != ended_at
                    or session.capture_end_reason and session.capture_end_reason != reason_code):
                raise CaptureError("CONFIRMATION_CONFLICT")
            if last_sequence is not None:
                if last_sequence < session.next_sequence - 1:
                    raise CaptureError("INVALID_FINAL_SEQUENCE")
                if session.final_sequence is not None and session.final_sequence != last_sequence:
                    raise CaptureError("CONFIRMATION_CONFLICT")
            if reason_code in {"AGENT_INTERRUPTED", "DISK_LOW"}:
                if session.state == SessionState.COMPLETED:
                    # El reporte HTTPS puede llegar después del ACK legado y
                    # acredita un fallo real aunque ya esté toda la recepción.
                    session.state = SessionState.FAILED
                    session.error_code = "AGENT_INTERRUPTED"
                    session.save(update_fields=["state", "error_code"])
                    _event(session, "session.failed", now, error_code="AGENT_INTERRUPTED")
                else:
                    self._fail(session, "AGENT_INTERRUPTED", now)
            if (session.actual_end == ended_at and session.capture_end_reason == reason_code
                    and (last_sequence is None or session.final_sequence == last_sequence)):
                return _snapshot(session)
            self._stop(session, now)
            session.actual_end = ended_at
            session.capture_end_reason = reason_code
            if last_sequence is not None:
                session.final_sequence = last_sequence
            if session.final_sequence is None:
                session.reception_intervention_at = session.reception_intervention_at or now
                session.diagnostic_code = "FINAL_SEQUENCE_UNKNOWN"
            elif session.diagnostic_code == "FINAL_SEQUENCE_UNKNOWN":
                session.reception_intervention_at = None
                session.diagnostic_code = ""
            session.save(update_fields=["actual_end", "capture_end_reason", "final_sequence", "reception_intervention_at", "diagnostic_code"])
            _event(session, "capture.ended", now)
            self._expire(session, now)
            self._complete(session, now)
            return _snapshot(session)

    def inspection(self, box, session_id, *, now=None):
        """Proyección operativa independiente del DTO y estados del protocolo legado."""
        now = _instant(now)
        with transaction.atomic():
            session = self._load(box, session_id)
            self._expire(session, now)
            received = session.final_sequence is not None and session.next_sequence == session.final_sequence + 1
            jobs = FragmentJob.objects.filter(sequence__session=session)
            counts = {state: jobs.filter(state=state).count() for state in FragmentJob.State.values}
            pending = counts[FragmentJob.State.PENDING] + counts[FragmentJob.State.PROCESSING]
            cutoff = self._capture_limit(session)
            age = max(0, (now - cutoff).total_seconds()) if not received and now >= cutoff else 0
            backlog_alert = "critical" if age >= 72 * 3600 else "warning" if age >= 24 * 3600 else "notice" if age >= 15 * 60 else ""
            return {
                "session_id": str(session.pk), "box": session.box, "state": session.state,
                "capture": "finished" if session.actual_end is not None else "stop_unconfirmed" if session.state in (SessionState.STOPPING, SessionState.FAILED) else "active" if session.actual_start else "start_unconfirmed",
                "reception": "complete" if received else "intervention_required" if session.reception_intervention_at else "pending",
                "processing": ("intervention_required" if counts[FragmentJob.State.REVIEW]
                               else "pending" if pending or not received
                               else "failed" if counts[FragmentJob.State.FAILED] else "complete"),
                "next_sequence": session.next_sequence, "final_sequence": session.final_sequence,
                "actual_start": session.actual_start.isoformat() if session.actual_start else None,
                "actual_end": session.actual_end.isoformat() if session.actual_end else None,
                "capture_end_reason": session.capture_end_reason,
                "capture_limit": cutoff.isoformat(), "reception_deadline": self._reception_deadline(session).isoformat(),
                "diagnostic_code": session.diagnostic_code, "error_code": session.error_code,
                "job_counts": counts, "backlog_alert": backlog_alert,
            }

    def interrupted(self, box, session_id, *, error_code="AGENT_INTERRUPTED", now=None):
        if error_code not in TECHNICAL_ERRORS:
            raise CaptureError("INVALID_TECHNICAL_ERROR")
        now = _instant(now)
        with transaction.atomic():
            session = self._load(box, session_id)
            self._fail(session, error_code, now)
            return _snapshot(session)
