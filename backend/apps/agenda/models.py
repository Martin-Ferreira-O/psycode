import uuid
from django.db import models

class AgendaCollection(models.Model):
    generation = models.BigAutoField(primary_key=True)
    collection_id = models.UUIDField(default=uuid.uuid4, unique=True)
    source = models.CharField(max_length=64)
    agent_id = models.CharField(max_length=64)
    issued_at = models.DateTimeField(auto_now_add=True)
    received_at = models.DateTimeField(null=True)
    checksum = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict)
    outcome = models.CharField(max_length=16, blank=True)
    # Preservar el reporte original completo; la ocupación es una vista derivada.
    report = models.BinaryField(null=True)
    # Alcance fijado al emitir/confirmar la recolección; conserva reintentos en vuelo.
    scope = models.JSONField(default=dict)

class AgendaBoxRevision(models.Model):
    box = models.CharField(max_length=16, primary_key=True)
    collection = models.ForeignKey(AgendaCollection, on_delete=models.PROTECT)
    appointments = models.JSONField(default=list)


class SmileRoom(models.Model):
    """Sala física verificada en el selector de Smile, independiente del PC."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.CharField(max_length=64)
    smile_box_id = models.CharField(max_length=12)
    box = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=100)
    available = models.BooleanField(default=True)
    legacy_blocked_at = models.DateTimeField(null=True)
    last_seen_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['source', 'smile_box_id'], name='agenda_unique_smile_room')]


class SmileCatalogState(models.Model):
    source = models.CharField(max_length=64, primary_key=True)
    generation = models.PositiveBigIntegerField(default=0)
    digest = models.CharField(max_length=64, blank=True)
    synced_at = models.DateTimeField(null=True)
