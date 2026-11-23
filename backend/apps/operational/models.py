from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from backend.common.processing_models import JEV_DEFAULT_THRESHOLD, JevVersion, SpeechmaticsModel


class NotificationMode(models.TextChoices):
    DISTRIBUTION_LIST = "lista_distribucion", "Lista de distribución"
    ACTIVE_SUPERVISORS = "supervisores_activos", "Supervisores activos"


class AudioChunkMode(models.TextChoices):
    FIXED = "fixed", "Duración fija"
    SESSION = "session", "Sesión completa"


class SmileFormat(models.TextChoices):
    JSON = "smile.json.v1", "JSON"
    EXCEL = "smile.excel.v1", "Excel (XLSX)"


SMILE_TIMEZONE = "America/Santiago"
SMILE_FIELDS = (
    "smile_collector_id", "smile_source", "smile_url", "smile_interval", "smile_timeout",
    "smile_request_timeout", "smile_format", "smile_boxes",
)


class OperationalConfiguration(models.Model):
    """Configuración operativa única de la clínica (garantizada por id = 1)."""
    id = models.IntegerField(primary_key=True, default=1, editable=False)
    enabled_days = models.JSONField(default=list)  # Lista de enteros [0-6] (0 = Lunes)
    open_time = models.CharField(max_length=5)     # Formato "HH:MM"
    close_time = models.CharField(max_length=5)    # Formato "HH:MM"
    notification_mode = models.CharField(
        max_length=20, choices=NotificationMode.choices, default=NotificationMode.DISTRIBUTION_LIST,
    )
    primary_email = models.EmailField(max_length=254, blank=True)  # Correo de la lista de distribución
    backup_enabled = models.BooleanField(default=False)
    backup_email = models.EmailField(max_length=254, blank=True)
    audio_chunk_duration = models.IntegerField(default=60, validators=[MinValueValidator(10)])
    audio_chunk_mode = models.CharField(max_length=7, choices=AudioChunkMode.choices, default=AudioChunkMode.FIXED)
    jev_model = models.CharField(max_length=4, choices=JevVersion.choices, default=JevVersion.V114)
    jev_threshold = models.FloatField(
        default=JEV_DEFAULT_THRESHOLD, validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    speechmatics_model = models.CharField(
        max_length=8, choices=SpeechmaticsModel.choices, default=SpeechmaticsModel.ENHANCED,
    )
    smile_collector = models.ForeignKey("capture.AgentRegistration", on_delete=models.SET_NULL, null=True, blank=True)
    smile_source = models.CharField(max_length=64, default="smile")
    smile_url = models.URLField(max_length=2048, blank=True, default="")
    smile_interval = models.PositiveIntegerField(default=300)
    smile_timeout = models.PositiveIntegerField(default=300)
    smile_request_timeout = models.PositiveIntegerField(default=30)
    smile_format = models.CharField(max_length=14, choices=SmileFormat.choices, default=SmileFormat.JSON)
    smile_boxes = models.JSONField(default=list)
    smile_revision = models.PositiveBigIntegerField(default=0, editable=False)
    smile_legacy_sources = models.JSONField(default=dict, editable=False)
    timezone = models.CharField(max_length=50, default="America/Santiago")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "operational_configuration"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(audio_chunk_duration__gte=10),
                name="operational_audio_duration_min",
            ),
            models.CheckConstraint(
                condition=models.Q(audio_chunk_mode__in=AudioChunkMode.values),
                name="operational_valid_audio_mode",
            ),
            models.CheckConstraint(
                condition=models.Q(notification_mode__in=NotificationMode.values),
                name="operational_valid_notification_mode",
            ),
            models.CheckConstraint(condition=models.Q(jev_model__in=JevVersion.values), name="operational_valid_jev_model"),
            models.CheckConstraint(
                condition=models.Q(jev_threshold__range=(0, 1)), name="operational_valid_jev_threshold",
            ),
            models.CheckConstraint(
                condition=models.Q(speechmatics_model__in=SpeechmaticsModel.values),
                name="operational_valid_speechmatics_model",
            ),
            models.CheckConstraint(
                condition=(models.Q(smile_format__in=SmileFormat.values, smile_interval__range=(1, 86400),
                                    smile_timeout__range=(1, 3600), smile_request_timeout__range=(1, 300))
                           & models.Q(smile_timeout__gte=models.F("smile_request_timeout"))),
                name="operational_valid_smile_limits",
            ),
        ]

    def save(self, *args, **kwargs):
        self.pk = 1  # Forzar siempre a que sea la única fila
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "enabled_days": [0, 1, 2, 3, 4],  # Lunes a Viernes por defecto
                "open_time": "08:00",
                "close_time": "18:00",
                "primary_email": "",
                "backup_email": "",
                "smile_url": settings.SMILE_DEFAULT_URL,
            },
        )
        return obj


class AudioChunkConfigurationChange(models.Model):
    """Auditoría SQL técnica; conserva solo el identificador del actor y ajustes de audio."""

    actor_id = models.CharField(max_length=128)
    before_duration = models.IntegerField()
    after_duration = models.IntegerField()
    before_mode = models.CharField(max_length=7, choices=AudioChunkMode.choices)
    after_mode = models.CharField(max_length=7, choices=AudioChunkMode.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "operational_audio_chunk_change"
