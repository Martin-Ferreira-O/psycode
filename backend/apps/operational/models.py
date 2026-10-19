from django.db import models


class OperationalConfiguration(models.Model):
    """Configuración operativa única de la clínica (garantizada por id = 1)."""
    id = models.IntegerField(primary_key=True, default=1, editable=False)
    enabled_days = models.JSONField(default=list)  # Lista de enteros [0-6] (0 = Lunes)
    open_time = models.CharField(max_length=5)     # Formato "HH:MM"
    close_time = models.CharField(max_length=5)    # Formato "HH:MM"
    primary_email = models.EmailField(max_length=254)  # Correo principal del cliente
    backup_email = models.EmailField(max_length=254)   # Correo de respaldo (Sergio)
    timezone = models.CharField(max_length=50, default="America/Santiago")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "operational_configuration"

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