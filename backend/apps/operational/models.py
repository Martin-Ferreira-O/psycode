from django.db import models


class NotificationMode(models.TextChoices):
    DISTRIBUTION_LIST = "lista_distribucion", "Lista de distribución"
    ACTIVE_SUPERVISORS = "supervisores_activos", "Supervisores activos"


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
    timezone = models.CharField(max_length=50, default="America/Santiago")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "operational_configuration"
        constraints = [
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
