from django.core.validators import MinValueValidator
from django.db import models


class NotificationMode(models.TextChoices):
    DISTRIBUTION_LIST = "lista_distribucion", "Lista de distribución"
    ACTIVE_SUPERVISORS = "supervisores_activos", "Supervisores activos"


class AudioChunkMode(models.TextChoices):
    FIXED = "fixed", "Duración fija"
    SESSION = "session", "Sesión completa"


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
