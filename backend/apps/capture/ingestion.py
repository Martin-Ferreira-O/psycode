import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.db import transaction

from .audio_tests import accept_test_sequence, load_test
from .domain import CaptureError
from .models import AUDIO_TEST_ORIGIN, AcceptedSequence, CaptureSession, FragmentJob
from .services import CaptureSessionService, _box, _event, _instant, _uuid
from .storage import FragmentError


@dataclass(frozen=True)
class FragmentReceipt:
    job_id: UUID
    session_id: UUID
    box: str
    sequence: int
    format: str
    checksum: str
    size: int
    accepted_at: datetime


def receipt(job, session, sequence):
    return FragmentReceipt(job.pk, session.pk, session.box, sequence.number, job.format,
                           job.checksum, job.size, sequence.accepted_at)


class FragmentIngestionService:
    def __init__(self, storage, control=None):
        self.storage = storage
        self.control = control if control is not None else CaptureSessionService()

    def receive(self, *, box, session_id, number, format, checksum, captured_at, upload, now=None, temporal=None,
                agent_id="", test_agent=None):
        box, session_id = _box(box), _uuid(session_id)
        captured_at = _instant(captured_at) if captured_at is not None else None
        if captured_at is None:
            raise CaptureError("INVALID_TIMESTAMP")
        if type(number) is not int or not 0 <= number <= 9223372036854775806:
            raise CaptureError("INVALID_SEQUENCE")
        if format != "wav":
            raise FragmentError("FRAGMENT_FORMAT_UNSUPPORTED", 415)
        if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise FragmentError("VALIDATION_ERROR", 400)
        try:
            if test_agent is None:
                self.control._recover_one(box, session_id, _instant(now))
            else:
                load_test(session_id, test_agent)
            from .chunk_config import byte_limit
            session = (load_test(session_id, test_agent).session if test_agent is not None else
                       CaptureSession.objects.filter(pk=session_id, box=box).exclude(origin=AUDIO_TEST_ORIGIN).first())
            if session is None:
                raise CaptureError("SESSION_NOT_FOUND")
            if session.capture_chunk_negotiated is True and temporal is None:
                raise FragmentError("AUDIO_VERSION_CONFLICT", 409)
            limit = byte_limit(session, self.storage.max_bytes)
            with self.storage.stage(upload, checksum, max_bytes=limit) as stored:
                received_at = _instant(now)
                if test_agent is None:
                    self.control._recover_one(box, session_id, received_at)
                with transaction.atomic(durable=True):
                    run = load_test(session_id, test_agent, lock=True) if test_agent is not None else None
                    session = run.session if run is not None else self.control._load(box, session_id)
                    sequence = AcceptedSequence.objects.filter(session=session, number=number).first()
                    if sequence:
                        job = FragmentJob.objects.filter(sequence=sequence).first()
                        if job is None:
                            raise FragmentError("SEQUENCE_ALREADY_REGISTERED", 409)
                        if (job.checksum != stored.checksum or job.format != format or job.size != stored.size
                                or sequence.captured_at != captured_at or job.temporal != (temporal or {})):
                            raise FragmentError("SEQUENCE_CONFLICT", 409)
                        return receipt(job, session, sequence), False
                    if run is not None:
                        accept_test_sequence(run, number, captured_at, received_at, temporal)
                    if temporal is not None:
                        from .temporal import validate
                        validate(temporal, upload, session, number, captured_at, received_at)
                    elif session.audio_profile:
                        raise FragmentError("AUDIO_VERSION_CONFLICT", 409)
                    if run is None:
                        self.control._accept_sequence(session, number, captured_at, received_at)
                    sequence = AcceptedSequence.objects.get(session=session, number=number)
                    sequence.agent_id = agent_id
                    sequence.save(update_fields=["agent_id"])
                    job = FragmentJob.objects.create(sequence=sequence, storage_key=stored.key,
                                                     checksum=stored.checksum, format=format, size=stored.size, temporal=temporal or {})
                    _event(session, "fragment.queued", received_at, sequence=number)
                    result = receipt(job, session, sequence)
                    stored.keep = True
                return result, True
        except CaptureError as exc:
            if exc.code == "SESSION_NOT_FOUND":
                raise FragmentError("SESSION_NOT_FOUND", 404) from None
            raise
        except OSError:
            raise FragmentError("FRAGMENT_STORAGE_UNAVAILABLE", 503) from None
