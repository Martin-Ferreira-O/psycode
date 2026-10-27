import wave
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from django.db import transaction
from django.utils import timezone

from backend.apps.analysis.domain import AnalysisState, Fragment
from .models import FragmentJob, SessionState
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
                )

                roles = self.roles_provider(fragment)

                if not isinstance(roles, dict):
                    roles = {}

                analysis_started = True
                result = self.analysis.process(fragment, roles=roles)

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
                try:
                    with self.storage.lease(job.storage_key):
                        fragment_available = True
                except BlockingIOError:
                    continue
                except FragmentError:
                    fragment_available = False

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

            self._delete_final(storage_key)

        return len(recovered), len(failed)

    def _claim_next(self, now):
        with transaction.atomic():
            jobs = (
                FragmentJob.objects
                .select_for_update()
                .select_related("sequence__session")
                .filter(state=FragmentJob.State.PENDING)
                .order_by(
                    "sequence__accepted_at",
                    "sequence__session_id",
                    "sequence__number",
                    "job_id",
                )
            )

            for job in jobs:
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

    def _finish_completed(self, claimed, result, *, now):
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
                processing_started_at=None,
                processing_token=None,
                last_error_code="",
            )
        )

        if not updated:
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
        open_jobs = FragmentJob.objects.filter(
            sequence__session_id=session_id,
            state__in=[
                FragmentJob.State.PENDING,
                FragmentJob.State.PROCESSING,
            ],
        ).exists()

        if open_jobs:
            return

        terminal_session = FragmentJob.objects.filter(
            sequence__session_id=session_id,
            sequence__session__state__in=[
                SessionState.COMPLETED,
                SessionState.FAILED,
            ],
        ).exists()

        if terminal_session:
            self.analysis.close_session(session_id)

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

