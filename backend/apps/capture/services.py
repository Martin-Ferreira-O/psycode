"""Ciclo de captura y bandeja de órdenes durable; sin I/O del agente dentro de SQL."""
from datetime import datetime, timedelta
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from backend.common.audit import AuditWriter
from .domain import CaptureError, Command, Session, TECHNICAL_ERRORS
from .models import (
    OPEN_STATES, AcceptedSequence, AgentCommand, CaptureEvent, CaptureSession,
    CommandKind, SessionState,
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
    def __init__(self, authorization_service=None, *, start_timeout=timedelta(minutes=2),
                 heartbeat_timeout=timedelta(minutes=2), finalization_timeout=timedelta(minutes=5)):
        if any(value <= timedelta(0) for value in (start_timeout, heartbeat_timeout, finalization_timeout)):
            raise ValueError("Los tiempos de espera deben ser positivos")
        self.authorization_service = authorization_service
        self.start_timeout = start_timeout
        self.heartbeat_timeout = heartbeat_timeout
        self.finalization_timeout = finalization_timeout

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
            current = CaptureSession.objects.select_for_update().filter(box=box, state__in=OPEN_STATES).first()
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
            if AgentCommand.objects.filter(session__box=box, kind=CommandKind.STOP).exclude(succeeded=True).exists():
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
                existing = CaptureSession.objects.filter(box=box, state__in=OPEN_STATES).first()
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
        session.save(update_fields=["state", "error_code", "closed_at"])
        _event(session, "session.failed", now, error_code=code)

    def _complete(self, session, now):
        if (session.state == SessionState.STOPPING and session.actual_end is not None
                and session.final_sequence is not None and session.next_sequence == session.final_sequence + 1):
            session.state, session.closed_at = SessionState.COMPLETED, now
            session.save(update_fields=["state", "closed_at"])
            _event(session, "session.completed", now)

    def _expire(self, session, now):
        if session.state in (SessionState.STARTED, SessionState.ACTIVE) and now >= session.scheduled_end:
            self._stop(session, now)
        if session.state == SessionState.STOPPING:
            if now >= session.stop_requested_at + self.finalization_timeout:
                self._fail(session, "FINAL_SEQUENCE_TIMEOUT" if session.actual_end else "SESSION_ABANDONED", now)
        elif session.state == SessionState.STARTED and now >= session.authorized_at + self.start_timeout:
            self._fail(session, "AGENT_UNAVAILABLE", now)
        elif session.state == SessionState.ACTIVE and now >= session.last_seen_at + self.heartbeat_timeout:
            self._fail(session, "SESSION_ABANDONED", now)

    def recover(self, *, now=None):
        """Una pasada recuperable tras reinicio; ejecutar periódicamente."""
        now, changed = _instant(now), 0
        ids = list(CaptureSession.objects.filter(state__in=OPEN_STATES).values_list("pk", flat=True))
        for session_id in ids:
            with transaction.atomic():
                session = CaptureSession.objects.select_for_update().get(pk=session_id)
                previous = session.state
                self._expire(session, now)
                changed += previous != session.state
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
                                      item.session.scheduled_start, item.session.scheduled_end))
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
            if success and command.kind == CommandKind.STOP and occurred < command.created_at:
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
                session.actual_end, session.final_sequence = occurred, last_sequence
            command.acknowledged_at, command.succeeded = now, success
            command.occurred_at, command.last_sequence, command.error_code = occurred, last_sequence, code
            command.save(update_fields=["acknowledged_at", "succeeded", "occurred_at", "last_sequence", "error_code"])
            session.last_seen_at = max(session.last_seen_at, now)
            session.save(update_fields=["state", "actual_start", "actual_end", "final_sequence", "last_seen_at"])
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
        if session.state not in (SessionState.ACTIVE, SessionState.STOPPING) or session.actual_start is None:
            raise CaptureError("SESSION_NOT_ACCEPTING_SEQUENCES")
        if number != session.next_sequence or (session.final_sequence is not None and number > session.final_sequence):
            raise CaptureError("SEQUENCE_OUT_OF_ORDER")
        upper = min(value for value in (session.scheduled_end, session.stop_requested_at, session.actual_end, now)
                    if value is not None)
        if not session.actual_start <= captured_at <= upper:
            raise CaptureError("SEQUENCE_OUTSIDE_CAPTURE_WINDOW")
        previous = AcceptedSequence.objects.filter(session=session, number=number - 1).first()
        if previous and captured_at < previous.captured_at:
            raise CaptureError("INVALID_TIMESTAMP")
        AcceptedSequence.objects.create(session=session, number=number, captured_at=captured_at, accepted_at=now)
        session.next_sequence += 1
        session.last_seen_at = max(session.last_seen_at, now)
        session.save(update_fields=["next_sequence", "last_seen_at"])
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
                session.save(update_fields=["last_seen_at"])
            return _snapshot(session)

    def interrupted(self, box, session_id, *, error_code="AGENT_INTERRUPTED", now=None):
        if error_code not in TECHNICAL_ERRORS:
            raise CaptureError("INVALID_TECHNICAL_ERROR")
        now = _instant(now)
        with transaction.atomic():
            session = self._load(box, session_id)
            self._fail(session, error_code, now)
            return _snapshot(session)
