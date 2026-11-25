from datetime import datetime, timedelta
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Exists, F, OuterRef, Q
from django.utils import timezone

from backend.common.audit import AuditWriter
from backend.common.boxes import is_box
from . import chunk_config
from .domain import CaptureError, Command, Session, TECHNICAL_ERRORS
from .models import (
    AUDIO_TEST_ORIGIN, OPEN_STATES, AcceptedSequence, AgentCommand, CaptureEvent, CaptureSession,
    CommandKind, FragmentJob, SessionState,
)

STOP_CONFIRMATION_ESCALATED = "STOP_CONFIRMATION_ESCALATED"
STOP_CONFIRMATION_DIAGNOSTICS = {"STOP_CONFIRMATION_PENDING", STOP_CONFIRMATION_ESCALATED}


def _unconfirmed_stops():
    return AgentCommand.objects.filter(kind=CommandKind.STOP).exclude(succeeded=True)


def _failed_with_pending_stop():
    return Q(state=SessionState.FAILED, actual_end=None) & Exists(
        _unconfirmed_stops().filter(session_id=OuterRef("pk")),
    )


def _sessions_pending_stop():
    return CaptureSession.objects.filter(actual_end=None).filter(
        Q(state__in=OPEN_STATES) | _failed_with_pending_stop(),
    )


def _undelivered_start_sessions(now):
    delivery_evidence = CaptureEvent.objects.filter(
        session_id=OuterRef("session_id"), command_id=OuterRef("pk"),
        action__in=("capture.command.delivered", "capture.command.acknowledged"),
    )
    start = AgentCommand.objects.filter(
        session_id=OuterRef("pk"), kind=CommandKind.START,
        created_at__lte=OuterRef("stop_requested_at"), cancelled_at__gte=F("created_at"), cancelled_at__lte=now,
        delivery_count=0, delivered_at=None, acknowledged_at=None, succeeded=None,
        occurred_at=None, last_sequence=None, error_code="",
    ).filter(~Exists(delivery_evidence))
    conflicting_stop = AgentCommand.objects.filter(
        session_id=OuterRef("pk"), kind=CommandKind.STOP,
    ).filter(Q(succeeded=True) | Q(last_sequence__gte=0))
    capture_evidence = CaptureEvent.objects.filter(
        session_id=OuterRef("pk"), action__in=("capture.sequence.accepted", "capture.capture.ended"),
    )
    return CaptureSession.objects.filter(
        Q(final_sequence=None) | Q(final_sequence=-1),
        Exists(start), ~Exists(conflicting_stop), ~Exists(capture_evidence),
        ~Exists(AcceptedSequence.objects.filter(session_id=OuterRef("pk"))),
        state__in=(SessionState.STOPPING, SessionState.FAILED),
        actual_start=None, actual_end=None, next_sequence=0,
        stop_requested_at__range=(F("authorized_at"), now),
    )


def _instant(value=None):
    value = timezone.now() if value is None else value
    if not isinstance(value, datetime) or timezone.is_naive(value):
        raise CaptureError("INVALID_TIMESTAMP")
    return value


def _box(value):
    if type(value) is int or (isinstance(value, str) and value.isdigit()):
        value = f"box-{value}"
    if not is_box(value):
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
        with transaction.atomic():
            ending = CaptureSession.objects.select_for_update().filter(box=box, authorization_ended_at=None)
            if authorization.authorized:
                ending = ending.exclude(origin=authorization.origen, scheduled_start=start, scheduled_end=end)
            for previous in ending.order_by("pk"):
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
            if _unconfirmed_stops().filter(session__box=box, session__actual_end=None).exists():
                return None
            previous = CaptureSession.objects.filter(
                box=box, origin=authorization.origen, scheduled_start=start, scheduled_end=end,
                authorization_ended_at=None,
            ).first()
            if previous:
                if previous.actual_end is None or previous.capture_end_reason not in {"RECOVERY_STOPPED", "SHUTDOWN"}:
                    return _snapshot(previous)
                previous.authorization_ended_at = now
                previous.save(update_fields=["authorization_ended_at"])
                _event(previous, "authorization.ended", now)
            try:
                with transaction.atomic():
                    session = CaptureSession.objects.create(
                        box=box, state=SessionState.STARTED, origin=authorization.origen,
                        scheduled_start=start, scheduled_end=end, authorized_at=now, last_seen_at=now,
                        capture_chunk_config=chunk_config.snapshot(),
                    )
            except IntegrityError:
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

    def _stop(self, session, now, *, complete=True, end_reported=False):
        if session.state not in (SessionState.STARTED, SessionState.ACTIVE):
            return
        session.state = SessionState.STOPPING
        session.stop_requested_at = now
        session.save(update_fields=["state", "stop_requested_at"])
        AgentCommand.objects.filter(
            session=session, kind=CommandKind.START, acknowledged_at=None, cancelled_at=None,
        ).update(cancelled_at=now)
        if not end_reported and self._close_undelivered_start(session, now):
            if complete:
                self._complete(session, now)
            return
        self._command(session, CommandKind.STOP, now)
        _event(session, "session.stopping", now)

    def _close_undelivered_start(self, session, now):
        if (session.state not in (SessionState.STOPPING, SessionState.FAILED)
                or session.actual_end is not None or session.stop_requested_at is None):
            return False
        if not _undelivered_start_sessions(now).filter(pk=session.pk).exists():
            return False
        start = session.commands.get(kind=CommandKind.START)
        session.actual_end = session.stop_requested_at
        session.final_sequence = -1
        session.capture_end_reason = "RECOVERY_STOPPED"
        session.diagnostic_code = ""
        session.save(update_fields=["actual_end", "final_sequence", "capture_end_reason", "diagnostic_code"])
        _event(session, "start.cancelled_before_delivery", now, command=start)
        return True

    def _fail(self, session, code, now, *, end_reported=False):
        if session.state not in OPEN_STATES:
            return
        self._stop(session, now, complete=False, end_reported=end_reported)
        session.state, session.error_code, session.closed_at = SessionState.FAILED, code, now
        if session.diagnostic_code not in STOP_CONFIRMATION_DIAGNOSTICS:
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
        if code != STOP_CONFIRMATION_ESCALATED or not session.events.filter(
                action="capture.session.diagnostic", error_code=code).exists():
            _event(session, "session.diagnostic", now, error_code=code)

    def _expire(self, session, now):
        if session.state in (SessionState.STARTED, SessionState.ACTIVE) and now >= session.scheduled_end:
            self._stop(session, now)
        if session.state == SessionState.STOPPING or (session.state == SessionState.FAILED
                and (session.actual_end is not None or _unconfirmed_stops().filter(session=session).exists())):
            if (session.actual_end is not None and session.final_sequence is not None
                    and session.next_sequence == session.final_sequence + 1):
                return
            reception_overdue = now >= self._reception_deadline(session)
            if reception_overdue:
                if session.reception_intervention_at is None:
                    session.reception_intervention_at = now
                    session.save(update_fields=["reception_intervention_at"])
            waiting_for_stop = session.actual_end is None and session.stop_requested_at is not None
            if waiting_for_stop and now >= session.stop_requested_at + timedelta(hours=1):
                self._diagnose(session, STOP_CONFIRMATION_ESCALATED, now)
            elif reception_overdue:
                self._diagnose(session, "RECEPTION_INTERVENTION_REQUIRED", now)
            elif waiting_for_stop and now >= session.stop_requested_at + self.finalization_timeout:
                self._diagnose(session, "STOP_CONFIRMATION_PENDING", now)
        elif session.state == SessionState.STARTED and now >= session.authorized_at + self.start_timeout:
            self._diagnose(session, "START_CONFIRMATION_PENDING", now)
        elif session.state == SessionState.ACTIVE and now >= session.last_seen_at + self.heartbeat_timeout:
            self._diagnose(session, "CONTROL_DISCONNECTED", now)

    def recover(self, *, now=None):
        now, changed = _instant(now), 0
        ids = list(CaptureSession.objects.filter(
            Q(state__in=OPEN_STATES) | _failed_with_pending_stop(),
        ).order_by("pk").values_list("pk", flat=True))
        for session_id in ids:
            with transaction.atomic():
                session = CaptureSession.objects.select_for_update().get(pk=session_id)
                previous = (session.state, session.actual_end, session.diagnostic_code, session.reception_intervention_at)
                if self._close_undelivered_start(session, now):
                    self._complete(session, now)
                    changed += 1
                else:
                    self._expire(session, now)
                    changed += previous != (
                        session.state, session.actual_end, session.diagnostic_code, session.reception_intervention_at,
                    )
        return changed

    def count_pending_drain(self, *, now=None):
        proven_closed = _undelivered_start_sessions(_instant(now)).values("pk")
        return _sessions_pending_stop().exclude(pk__in=proven_closed).count()

    def _load(self, box, session_id):
        session = (CaptureSession.objects.select_for_update().filter(pk=_uuid(session_id), box=_box(box))
                   .exclude(origin=AUDIO_TEST_ORIGIN).first())
        if session is None:
            raise CaptureError("SESSION_NOT_FOUND")
        return session

    def commands(self, box, *, now=None, chunk_config_supported=None, chunk_config_v2_supported=False,
                 limit=None, reconcile=True, redelivery_seconds=0, configuration_pending=False):
        now, box = _instant(now), _box(box)
        with transaction.atomic():
            sessions = list(_sessions_pending_stop().select_for_update().filter(box=box).order_by("pk"))
            if reconcile:
                for session in sessions:
                    self._expire(session, now)
            pending = AgentCommand.objects.filter(
                session_id__in=[session.pk for session in sessions], session__actual_end=None, cancelled_at=None,
            ).exclude(succeeded=True)
            pending = pending.exclude(kind=CommandKind.START, acknowledged_at__isnull=False)
            stops = pending.filter(kind=CommandKind.STOP)
            if stops.exists():
                pending = stops
            pending = pending.select_for_update(of=("self",)).select_related("session").order_by("created_at", "command_id")
            commands = list(pending[:limit]) if limit is not None else list(pending)
            result = []
            for item in commands:
                session = item.session
                if item.kind == CommandKind.START and configuration_pending:
                    continue
                if (item.kind == CommandKind.START and session.capture_chunk_negotiated is True
                        and chunk_config_supported is not None
                        and (not chunk_config_supported or (chunk_config.overlap(session) == 0
                                                           and not chunk_config_v2_supported))):
                    self._diagnose(session, "CAPABILITIES_CHANGED", now)
                    continue
                if item.kind == CommandKind.START and session.diagnostic_code == "CAPABILITIES_CHANGED":
                    self._diagnose(session, "", now)
                if (item.kind == CommandKind.START and session.capture_chunk_negotiated is None
                        and chunk_config_supported is not None):
                    session.capture_chunk_negotiated = bool(chunk_config_supported and session.capture_chunk_config)
                    if session.capture_chunk_negotiated:
                        session.capture_chunk_config = {**session.capture_chunk_config,
                            "audio_chunk_overlap": 0 if chunk_config_v2_supported else 1}
                    session.save(update_fields=["capture_chunk_negotiated", "capture_chunk_config"])
                if item.delivered_at is None or (now - item.delivered_at).total_seconds() >= redelivery_seconds:
                    item.delivered_at, item.delivery_count = now, item.delivery_count + 1
                    item.save(update_fields=["delivered_at", "delivery_count"])
                    _event(item.session, "command.delivered", now, command=item)
                result.append(Command(item.command_id, item.session_id, box, item.kind,
                                      item.session.scheduled_start, min(item.session.scheduled_end, item.session.stop_requested_at)
                                      if item.kind == CommandKind.STOP and item.session.stop_requested_at else item.session.scheduled_end,
                                      chunk_config.duration(session) if item.kind == CommandKind.START
                                      and session.capture_chunk_negotiated is True else None,
                                      0 if item.kind == CommandKind.START and session.capture_chunk_negotiated is True
                                      and chunk_config.overlap(session) == 0 else None))
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
                if not (command.kind == CommandKind.STOP and command.succeeded is False and success):
                    raise CaptureError("CONFIRMATION_CONFLICT")
            occurred = occurred or now
            if not session.authorized_at <= occurred <= now:
                raise CaptureError("INVALID_TIMESTAMP")
            if success and command.kind == CommandKind.START:
                cut = min(value for value in (session.scheduled_end, session.authorization_ended_at,
                                               command.cancelled_at, session.stop_requested_at, session.actual_end)
                          if value is not None)
                if occurred >= cut:
                    raise CaptureError("INVALID_TIMESTAMP")
                session.actual_start = occurred
                if session.state == SessionState.STARTED:
                    if now >= session.scheduled_end:
                        self._stop(session, now)
                    else:
                        session.state = SessionState.ACTIVE
            elif success:
                if (occurred < command.created_at and session.actual_end is None
                        and occurred < self._capture_limit(session) and session.actual_start is None
                        and last_sequence >= 0):
                    raise CaptureError("INVALID_TIMESTAMP")
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
                    or success and command.kind == CommandKind.STOP
                    and session.diagnostic_code in STOP_CONFIRMATION_DIAGNOSTICS):
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
        session.save(update_fields=["next_sequence"])
        _event(session, "sequence.accepted", now, sequence=number)
        self._complete(session, now)
        return True

    def _recover_one(self, box, session_id, now):
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
                    session.state = SessionState.FAILED
                    session.error_code = "AGENT_INTERRUPTED"
                    session.save(update_fields=["state", "error_code"])
                    _event(session, "session.failed", now, error_code="AGENT_INTERRUPTED")
                else:
                    self._fail(session, "AGENT_INTERRUPTED", now, end_reported=True)
            if (session.actual_end == ended_at and session.capture_end_reason == reason_code
                    and (last_sequence is None or session.final_sequence == last_sequence)):
                return _snapshot(session)
            self._stop(session, now, end_reported=True)
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
            elif session.diagnostic_code in STOP_CONFIRMATION_DIAGNOSTICS:
                session.diagnostic_code = ""
            session.save(update_fields=["actual_end", "capture_end_reason", "final_sequence", "reception_intervention_at", "diagnostic_code"])
            _event(session, "capture.ended", now)
            self._expire(session, now)
            self._complete(session, now)
            return _snapshot(session)

    def inspection(self, box, session_id, *, now=None):
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
