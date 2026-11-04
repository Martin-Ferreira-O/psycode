import wave
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from django.db import DatabaseError, transaction
from django.db.models import Q
from django.utils import timezone

from backend.apps.analysis.errors import AnalysisRetry
from backend.common.errors import PersistenceUnavailable
from backend.apps.analysis.domain import AnalysisContextLost, AnalysisState, Fragment
from .models import CaptureSession, FragmentJob, SessionState
from .storage import FragmentError


TECHNICAL_RESULT_CODES = frozenset({
    "SPEECHMATICS_FAILED",
    "SPEECHMATICS_DELETE_PENDING",
    "JEV_FAILED",
    "JEV_SUBMISSION_UNCERTAIN",
    "FLOW_INTERRUPTED",
    "ALERT_PERSISTENCE_FAILED",
})


@dataclass(frozen=True)
class ClaimedFragmentJob:
    job_id: UUID
    token: UUID
    storage_key: str
    session_id: str
    sequence: int
    box: str
    captured_at: object
    attempts: int
    temporal: dict
    error_code: str = ""
    checkpoint: dict | None = None
    session_start: object = None


@dataclass
class JobCheckpoint:
    job: ClaimedFragmentJob
    data: dict

    def save(self):
        updated = FragmentJob.objects.filter(
            pk=self.job.job_id, state=FragmentJob.State.PROCESSING,
            processing_token=self.job.token,
        ).update(checkpoint=self.data)
        if not updated:
            raise DatabaseError("Fragment job claim lost")


class QueueFragmentLedger:
    def claim(self, fragment):
        return None


class FragmentJobProcessor:
    def __init__(
        self,
        storage,
        analysis,
        *,
        roles_provider=None,
        audit=None,
        max_attempts=3,
        stuck_after=timedelta(minutes=5),
    ):
        if max_attempts <= 0:
            raise ValueError("Los intentos máximos deben ser positivos")

        if stuck_after <= timedelta(0):
            raise ValueError("El tiempo de atasco debe ser positivo")

        self.storage = storage
        self.analysis = analysis
        self.durable = callable(getattr(analysis, "resume", None))
        self.roles_provider = roles_provider or (lambda fragment: {})
        self.audit = audit
        self.max_attempts = max_attempts
        self.stuck_after = stuck_after

    def process_next(self, *, now=None):
        now = now or timezone.now()
        self.recover_stuck(now=now)

        claimed = self._claim_next(now)

        if claimed is None:
            return None

        if claimed.error_code:
            return self._finish_failed(claimed, claimed.error_code, now=timezone.now())

        if self.durable:
            return self._process_durable(claimed, now)

        analysis_started = False

        try:
            with self.storage.lease(claimed.storage_key) as path:
                frames = self._wav_frames(path)

                fragment = Fragment(
                    session_id=claimed.session_id,
                    sequence=claimed.sequence,
                    box=claimed.box,
                    captured_at=claimed.captured_at,
                    path=path,
                    start=0,
                    end=frames,
                    context_start=0,
                    session_origin_sample=claimed.temporal.get("session_start_sample", 0),
                    new_audio_start_sample=claimed.temporal.get("new_audio_start_sample"),
                )

                roles = self.roles_provider(fragment)

                if not isinstance(roles, dict):
                    roles = {}

                analysis_started = True
                result = self.analysis.process(fragment, roles=roles)

        except AnalysisContextLost:
            return self._finish_failed(claimed, "ANALYSIS_CONTEXT_LOST", now=timezone.now())

        except BlockingIOError:
            if analysis_started:
                return self._finish_failed(
                    claimed,
                    "FLOW_INTERRUPTED",
                    now=timezone.now(),
                    audit_failure=False,
                )

            return self._retry_local(
                claimed,
                now=timezone.now(),
            )

        except (FragmentError, OSError, wave.Error, ValueError):
            return self._finish_failed(
                claimed,
                "FLOW_INTERRUPTED",
                now=timezone.now(),
                audit_failure=not analysis_started,
            )

        except Exception:
            return self._finish_failed(
                claimed,
                "FLOW_INTERRUPTED",
                now=timezone.now(),
                audit_failure=not analysis_started,
            )

        technical_error = next(
            (
                code
                for code in result.error_codes
                if code in TECHNICAL_RESULT_CODES
            ),
            "",
        )

        if technical_error:
            return self._finish_failed(
                claimed,
                technical_error,
                now=timezone.now(),
                audit_failure=False,
            )

        result_value = {
            AnalysisState.SIGNAL: FragmentJob.Result.RISK_DETECTED,
            AnalysisState.NO_SIGNAL: FragmentJob.Result.NO_RISK_DETECTED,
            AnalysisState.INDETERMINATE: FragmentJob.Result.INDETERMINATE,
        }[result.state]

        return self._finish_completed(
            claimed,
            result_value,
            now=timezone.now(),
        )

    def _process_durable(self, claimed, now):
        checkpoint = JobCheckpoint(claimed, claimed.checkpoint)
        previous = FragmentJob.objects.filter(
            sequence__session_id=claimed.session_id,
            sequence__number=claimed.sequence - 1,
            state=FragmentJob.State.COMPLETED,
        ).values_list("checkpoint", flat=True).first() if claimed.sequence else {}
        if claimed.sequence and not previous:
            if previous is None or not checkpoint.data.get("accept_missing_context"):
                return self._reschedule(claimed, "ANALYSIS_CONTEXT_LOST", now, review=True)

        def run(path, frames, roles):
            fragment = Fragment(
                claimed.session_id, claimed.sequence, claimed.box,
                claimed.session_start or claimed.captured_at, path, end=frames,
                session_origin_sample=claimed.temporal.get("session_start_sample", 0),
                new_audio_start_sample=claimed.temporal.get("new_audio_start_sample"),
            )
            if roles:
                resolved_roles = self.roles_provider(fragment)
                roles = resolved_roles if isinstance(resolved_roles, dict) else {}
            return self.analysis.resume(fragment, roles=roles or {}, checkpoint=checkpoint, previous=previous)

        try:
            if "result" in checkpoint.data:
                result, context = run(None, checkpoint.data["frames"], False)
            else:
                with self.storage.lease(claimed.storage_key) as path:
                    frames = self._wav_frames(path)
                    checkpoint.data["frames"] = frames
                    result, context = run(path, frames, "roles" not in checkpoint.data)
        except DatabaseError:
            raise
        except AnalysisRetry as exc:
            return self._reschedule(claimed, exc.code, now, review=exc.code in {"JEV_SUBMISSION_UNCERTAIN", "NOTIFICATION_UNCERTAIN"})
        except PersistenceUnavailable:
            return self._reschedule(claimed, "ALERT_PERSISTENCE_FAILED", now)
        except Exception:
            return self._reschedule(claimed, "FLOW_INTERRUPTED", now)

        state = {
            AnalysisState.SIGNAL: FragmentJob.Result.RISK_DETECTED,
            AnalysisState.NO_SIGNAL: FragmentJob.Result.NO_RISK_DETECTED,
            AnalysisState.INDETERMINATE: FragmentJob.Result.INDETERMINATE,
        }[result.state]
        completed = self._finish_completed(claimed, state, now=timezone.now(), context=context)
        if completed and claimed.attempts > 1:
            self._audit_recovery(claimed.session_id, claimed.sequence)
        return completed

    def _reschedule(self, claimed, code, now, *, review=False):
        now = max(now, timezone.now())
        review = review or claimed.attempts >= self.max_attempts
        state = FragmentJob.State.REVIEW if review else FragmentJob.State.PENDING
        updated = FragmentJob.objects.filter(
            pk=claimed.job_id, state=FragmentJob.State.PROCESSING, processing_token=claimed.token,
        ).update(
            state=state, retry_at=None if review else now + timedelta(minutes=2 ** (claimed.attempts - 1)),
            processing_started_at=None, processing_token=None, last_error_code=code,
        )
        if updated:
            self._audit_failure(code, claimed.session_id, claimed.sequence)
            return state
        return None

    def recover_stuck(self, *, now=None):
        now = now or timezone.now()
        cutoff = now - self.stuck_after
        recovered = []
        failed = []

        with transaction.atomic():
            jobs = list(
                FragmentJob.objects
                .select_for_update()
                .select_related("sequence__session")
                .filter(
                    state=FragmentJob.State.PROCESSING,
                    processing_started_at__lte=cutoff,
                )
                .order_by("processing_started_at", "job_id")
            )

            for job in jobs:
                if self.durable and "result" in job.checkpoint:
                    fragment_available = True
                else:
                    try:
                        with self.storage.lease(job.storage_key):
                            fragment_available = True
                    except BlockingIOError:
                        continue
                    except FragmentError:
                        fragment_available = False

                if self.durable:
                    review = not fragment_available or job.attempts >= self.max_attempts
                    job.state = FragmentJob.State.REVIEW if review else FragmentJob.State.PENDING
                    job.processing_started_at = None
                    job.processing_token = None
                    job.last_error_code = "FLOW_INTERRUPTED"
                    job.save(update_fields=["state", "processing_started_at", "processing_token", "last_error_code"])
                    if review:
                        failed.append((None, str(job.sequence.session_id), job.sequence.number))
                    else:
                        recovered.append((str(job.sequence.session_id), job.sequence.number))
                    continue

                session_id = str(job.sequence.session_id)
                sequence = job.sequence.number

                if not fragment_available or job.attempts >= self.max_attempts:
                    job.state = FragmentJob.State.FAILED
                    job.result = ""
                    job.finished_at = now
                    job.last_error_code = "FLOW_INTERRUPTED"
                    job.processing_started_at = None
                    job.processing_token = None
                    job.save(
                        update_fields=[
                            "state",
                            "result",
                            "finished_at",
                            "last_error_code",
                            "processing_started_at",
                            "processing_token",
                        ]
                    )

                    failed.append(
                        (
                            job.storage_key,
                            session_id,
                            sequence,
                        )
                    )

                else:
                    job.state = FragmentJob.State.PENDING
                    job.processing_started_at = None
                    job.processing_token = None
                    job.last_error_code = "FLOW_INTERRUPTED"
                    job.save(
                        update_fields=[
                            "state",
                            "processing_started_at",
                            "processing_token",
                            "last_error_code",
                        ]
                    )

                    recovered.append(
                        (
                            session_id,
                            sequence,
                        )
                    )

        for session_id, sequence in recovered:
            self._audit_recovery(
                session_id,
                sequence,
            )

        for storage_key, session_id, sequence in failed:
            self._audit_failure(
                "FLOW_INTERRUPTED",
                session_id,
                sequence,
            )

            if storage_key is not None:
                self._delete_final(storage_key)

        return len(recovered), len(failed)

    def _claim_next(self, now):
        with transaction.atomic():
            jobs = (
                FragmentJob.objects
                .select_for_update()
                .select_related("sequence__session")
                .filter(state=FragmentJob.State.PENDING)
                .filter(Q(retry_at__isnull=True) | Q(retry_at__lte=now))
                .order_by(
                    "sequence__accepted_at",
                    "sequence__session_id",
                    "sequence__number",
                    "job_id",
                )
            )

            for job in jobs:
                error_code = ""
                blocked = (
                    FragmentJob.objects
                    .filter(
                        sequence__session_id=job.sequence.session_id,
                        sequence__number__lt=job.sequence.number,
                    )
                    .exclude(state=FragmentJob.State.COMPLETED)
                    .exists()
                )

                if blocked:
                    if self.durable:
                        continue
                    if FragmentJob.objects.filter(sequence__session_id=job.sequence.session_id,
                            sequence__number__lt=job.sequence.number, state=FragmentJob.State.FAILED).exists():
                        # Finalizar fuera de la transacción con la misma limpieza
                        # de archivos y contextos que cualquier otro fallo.
                        error_code = "PREVIOUS_FRAGMENT_FAILED"
                    else:
                        continue

                token = uuid4()

                job.state = FragmentJob.State.PROCESSING
                job.attempts += 1
                job.processing_started_at = now
                job.processing_token = token
                job.finished_at = None
                job.last_error_code = ""

                job.save(
                    update_fields=[
                        "state",
                        "attempts",
                        "processing_started_at",
                        "processing_token",
                        "finished_at",
                        "last_error_code",
                    ]
                )

                return ClaimedFragmentJob(
                    job_id=job.job_id,
                    token=token,
                    storage_key=job.storage_key,
                    session_id=str(job.sequence.session_id),
                    sequence=job.sequence.number,
                    box=job.sequence.session.box,
                    captured_at=job.sequence.captured_at,
                    attempts=job.attempts,
                    temporal=job.temporal,
                    error_code=error_code,
                    checkpoint=job.checkpoint,
                    session_start=job.sequence.session.actual_start,
                )

        return None

    def _retry_local(self, claimed, *, now):
        terminal = False

        with transaction.atomic():
            job = (
                FragmentJob.objects
                .select_for_update()
                .filter(
                    pk=claimed.job_id,
                    state=FragmentJob.State.PROCESSING,
                    processing_token=claimed.token,
                )
                .first()
            )

            if job is None:
                return None

            if job.attempts >= self.max_attempts:
                job.state = FragmentJob.State.FAILED
                job.result = ""
                job.finished_at = now
                terminal = True
            else:
                job.state = FragmentJob.State.PENDING
                job.finished_at = None

            job.processing_started_at = None
            job.processing_token = None
            job.last_error_code = "FLOW_INTERRUPTED"

            job.save(
                update_fields=[
                    "state",
                    "result",
                    "finished_at",
                    "processing_started_at",
                    "processing_token",
                    "last_error_code",
                ]
            )

        if terminal:
            self._audit_failure(
                "FLOW_INTERRUPTED",
                claimed.session_id,
                claimed.sequence,
            )

            self._delete_final(claimed.storage_key)

        return job.state

    @transaction.atomic
    def _confirm_result(self, claimed, result, *, now, context):
        fields = {"checkpoint": context, "retry_at": None} if context is not None else {}
        updated = (
            FragmentJob.objects
            .filter(
                pk=claimed.job_id,
                state=FragmentJob.State.PROCESSING,
                processing_token=claimed.token,
            )
            .update(
                state=FragmentJob.State.COMPLETED,
                result=result,
                finished_at=now,
                **fields,
                processing_started_at=None,
                processing_token=None,
                last_error_code="",
            )
        )

        if updated and context is not None and claimed.sequence:
            previous = FragmentJob.objects.filter(
                sequence__session_id=claimed.session_id, sequence__number=claimed.sequence - 1,
                state=FragmentJob.State.COMPLETED,
            ).first()
            if previous:
                previous.checkpoint.pop("history", None)
                previous.checkpoint.pop("evidence", None)
                previous.save(update_fields=["checkpoint"])
        return updated

    def _finish_completed(self, claimed, result, *, now, context=None):
        if not self._confirm_result(claimed, result, now=now, context=context):
            return None
        self._delete_final(claimed.storage_key)
        self._close_session_if_finished(claimed.session_id)
        return FragmentJob.State.COMPLETED

    def _finish_failed(
        self,
        claimed,
        error_code,
        *,
        now,
        audit_failure=True,
    ):
        updated = (
            FragmentJob.objects
            .filter(
                pk=claimed.job_id,
                state=FragmentJob.State.PROCESSING,
                processing_token=claimed.token,
            )
            .update(
                state=FragmentJob.State.FAILED,
                result="",
                finished_at=now,
                processing_started_at=None,
                processing_token=None,
                last_error_code=error_code,
            )
        )

        if not updated:
            return None

        if audit_failure:
            self._audit_failure(
                error_code,
                claimed.session_id,
                claimed.sequence,
            )

        self._delete_final(claimed.storage_key)
        self._close_session_if_finished(claimed.session_id)

        return FragmentJob.State.FAILED

    def _delete_final(self, storage_key):
        try:
            self.storage.delete(storage_key)

        except FragmentError as exc:
            if exc.code != "FRAGMENT_NOT_FOUND":
                return False

        except (BlockingIOError, OSError):
            return False

        return True

    def _close_session_if_finished(self, session_id):
        session = CaptureSession.objects.filter(
            pk=session_id,
            state__in=[SessionState.COMPLETED, SessionState.FAILED],
        ).first()
        # Una captura fallida puede terminar de recibir archivos válidos después
        # del cierre físico. El estado de captura no demuestra recepción completa.
        # Tampoco lo demuestra que momentáneamente no queden trabajos en SQL.
        if (session is None or session.actual_end is None or session.final_sequence is None
                or session.next_sequence != session.final_sequence + 1):
            return
        open_jobs = FragmentJob.objects.filter(
            sequence__session_id=session_id,
            state__in=[
                FragmentJob.State.PENDING,
                FragmentJob.State.PROCESSING,
                FragmentJob.State.REVIEW,
            ],
        ).exists()

        if open_jobs:
            return

        self.analysis.close_session(session_id)

    def close_finished_contexts(self):
        for session_id in list(getattr(self.analysis, "histories", {})):
            self._close_session_if_finished(session_id)

    def _audit_failure(self, code, session_id, sequence):
        if self.audit is not None:
            self.audit.failure(
                code,
                sesion_id=session_id,
                sequence=sequence,
            )

    def _audit_recovery(self, session_id, sequence):
        if self.audit is not None and hasattr(self.audit, "recovery"):
            self.audit.recovery(
                sesion_id=session_id,
                sequence=sequence,
            )

    @staticmethod
    def _wav_frames(path):
        with wave.open(str(path), "rb") as wav:
            if (
                wav.getnchannels() != 1
                or wav.getsampwidth() != 2
                or wav.getframerate() != 16000
                or wav.getcomptype() != "NONE"
            ):
                raise ValueError("Formato WAV incompatible")

            frames = wav.getnframes()

        if frames <= 0:
            raise ValueError("Fragmento vacío")

        return frames

