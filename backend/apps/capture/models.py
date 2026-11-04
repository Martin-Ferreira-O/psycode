"""Metadatos técnicos de captura; archivos privados referenciados por claves opacas."""
import uuid

from django.db import models


class SessionState(models.TextChoices):
    STARTED = "iniciada"
    ACTIVE = "activa"
    STOPPING = "finalizando"
    COMPLETED = "completada"
    FAILED = "fallida"


OPEN_STATES = (SessionState.STARTED, SessionState.ACTIVE, SessionState.STOPPING)


class CaptureSession(models.Model):
    session_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    box = models.CharField(max_length=16)
    state = models.CharField(max_length=16, choices=SessionState.choices)
    origin = models.CharField(max_length=24, choices=[("agenda", "Agenda"), ("horario_clinico", "Respaldo")])
    scheduled_start = models.DateTimeField()
    scheduled_end = models.DateTimeField()
    authorized_at = models.DateTimeField()
    authorization_ended_at = models.DateTimeField(null=True)
    actual_start = models.DateTimeField(null=True)
    actual_end = models.DateTimeField(null=True)
    capture_end_reason = models.CharField(max_length=40, blank=True, default="")
    stop_requested_at = models.DateTimeField(null=True)
    closed_at = models.DateTimeField(null=True)
    last_seen_at = models.DateTimeField()
    next_sequence = models.PositiveBigIntegerField(default=0)
    final_sequence = models.BigIntegerField(null=True)
    error_code = models.CharField(max_length=40, blank=True)
    diagnostic_code = models.CharField(max_length=40, blank=True, default="")
    reception_intervention_at = models.DateTimeField(null=True)
    reception_extended_until = models.DateTimeField(null=True)
    audio_profile = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["box"], condition=models.Q(state__in=OPEN_STATES, actual_end__isnull=True),
                                    name="capture_one_open_session_per_box"),
            models.UniqueConstraint(fields=["box", "origin", "scheduled_start", "scheduled_end"],
                                    condition=models.Q(authorization_ended_at__isnull=True),
                                    name="capture_one_session_per_authorization"),
            models.CheckConstraint(condition=models.Q(scheduled_end__gt=models.F("scheduled_start")),
                                   name="capture_valid_window"),
            models.CheckConstraint(condition=models.Q(final_sequence__isnull=True) | models.Q(final_sequence__gte=-1),
                                   name="capture_valid_final_sequence"),
            models.CheckConstraint(condition=models.Q(state__in=SessionState.values), name="capture_valid_state"),
            models.CheckConstraint(condition=models.Q(box__in=[f"box-{n}" for n in range(3, 8)]),
                                   name="capture_valid_box"),
        ]
        indexes = [models.Index(fields=["state", "last_seen_at"])]


class CommandKind(models.TextChoices):
    START = "inicio"
    STOP = "detencion"


class AgentCommand(models.Model):
    command_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(CaptureSession, on_delete=models.PROTECT, related_name="commands")
    kind = models.CharField(max_length=12, choices=CommandKind.choices)
    created_at = models.DateTimeField()
    delivered_at = models.DateTimeField(null=True)
    delivery_count = models.PositiveIntegerField(default=0)
    acknowledged_at = models.DateTimeField(null=True)
    succeeded = models.BooleanField(null=True)
    occurred_at = models.DateTimeField(null=True)
    last_sequence = models.BigIntegerField(null=True)
    error_code = models.CharField(max_length=40, blank=True)
    cancelled_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["session", "kind"], name="capture_unique_session_command")]


class AcceptedSequence(models.Model):
    session = models.ForeignKey(CaptureSession, on_delete=models.PROTECT, related_name="sequences")
    number = models.PositiveBigIntegerField()
    captured_at = models.DateTimeField()
    accepted_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["session", "number"], name="capture_unique_sequence")]


class CaptureEvent(models.Model):
    """Bitácora durable, guardada en la misma transacción que el cambio."""
    event_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(CaptureSession, on_delete=models.PROTECT, related_name="events")
    timestamp = models.DateTimeField()
    action = models.CharField(max_length=40)
    state = models.CharField(max_length=16, choices=SessionState.choices)
    sequence = models.PositiveBigIntegerField(null=True)
    command_id = models.UUIDField(null=True)
    error_code = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ["timestamp", "event_id"]

class FragmentJob(models.Model):
    """Cola SQL durable. Una secuencia aceptada solo puede tener un trabajo."""
    class State(models.TextChoices):
        PENDING = "pendiente"
        PROCESSING = "procesando"
        COMPLETED = "completado"
        FAILED = "fallido"
        REVIEW = "revision"

    class Result(models.TextChoices):
        RISK_DETECTED = "riesgo_detectado"
        NO_RISK_DETECTED = "sin_riesgo_detectado"
        INDETERMINATE = "indeterminado"

    job_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sequence = models.OneToOneField(AcceptedSequence, on_delete=models.PROTECT, related_name="fragment_job")
    temporal = models.JSONField(default=dict)
    checkpoint = models.JSONField(default=dict)
    retry_at = models.DateTimeField(null=True)
    storage_key = models.CharField(max_length=37, unique=True)
    checksum = models.CharField(max_length=64)
    format = models.CharField(max_length=8, default="wav")
    size = models.PositiveBigIntegerField()
    state = models.CharField(max_length=16, choices=State.choices, default=State.PENDING)
    result = models.CharField(max_length=24, choices=Result.choices, blank=True, default="")
    attempts = models.PositiveSmallIntegerField(default=0)
    processing_started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    last_error_code = models.CharField(max_length=40, blank=True)
    processing_token = models.UUIDField(null=True, editable=False)

    class Meta:
        indexes = [
            models.Index(fields=["state", "job_id"], name="capture_pending_jobs"),
            models.Index(fields=["state", "processing_started_at"], name="capture_job_recovery"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(state__in=["pendiente", "procesando", "completado", "fallido", "revision"]),
                name="capture_valid_job_state",
            ),
            models.CheckConstraint(
                condition=models.Q(result__in=["", "riesgo_detectado", "sin_riesgo_detectado", "indeterminado"]),
                name="capture_valid_job_result",
            ),
            models.CheckConstraint(condition=models.Q(size__gt=0), name="capture_nonempty_fragment"),
            models.CheckConstraint(condition=models.Q(format="wav"), name="capture_fragment_format"),
        ]


class RuntimeLease(models.Model):
    """Exclusión SQL entre procesos; un propietario por box o trabajador."""
    name = models.CharField(max_length=100, primary_key=True)
    owner = models.UUIDField()
    expires_at = models.DateTimeField()


class AgentStatus(models.Model):
    box = models.CharField(max_length=16, primary_key=True)
    seen_at = models.DateTimeField()
    diagnostics = models.JSONField(default=dict)


class AgentConnectivityEvent(models.Model):
    """Eventos locales inmutables, deduplicados por identidad autenticada y UUID."""
    event_id = models.UUIDField()
    agent_id = models.CharField(max_length=64)
    box = models.CharField(max_length=16)
    session_id = models.UUIDField(null=True)
    kind = models.CharField(max_length=40)
    occurred_at = models.DateTimeField()
    received_at = models.DateTimeField()
    outage_id = models.UUIDField(null=True)
    duration_ms = models.PositiveBigIntegerField(null=True)
    cause = models.CharField(max_length=40, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["agent_id", "event_id"], name="capture_unique_agent_event")]
        indexes = [models.Index(fields=["box", "occurred_at"], name="capture_agent_event_time")]
