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

class AgendaBoxRevision(models.Model):
    box = models.CharField(max_length=16, primary_key=True)
    collection = models.ForeignKey(AgendaCollection, on_delete=models.PROTECT)
    appointments = models.JSONField(default=list)
