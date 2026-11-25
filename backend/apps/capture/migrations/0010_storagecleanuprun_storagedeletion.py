
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('capture', '0009_fragmentjob_recovery'),
    ]

    operations = [
        migrations.CreateModel(
            name='StorageCleanupRun',
            fields=[
                ('run_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('started_at', models.DateTimeField()),
                ('finished_at', models.DateTimeField(null=True)),
                ('source', models.CharField(max_length=12)),
                ('actor_id', models.UUIDField(null=True)),
                ('outcome', models.CharField(default='running', max_length=12)),
                ('freed_bytes', models.PositiveBigIntegerField(default=0)),
                ('removed', models.PositiveIntegerField(default=0)),
                ('failures', models.PositiveIntegerField(default=0)),
                ('protected', models.PositiveIntegerField(default=0)),
                ('checkpoints', models.PositiveIntegerField(default=0)),
                ('error_code', models.CharField(blank=True, max_length=40)),
                ('audit_sent_at', models.DateTimeField(null=True)),
            ],
        ),
        migrations.CreateModel(
            name='StorageDeletion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(max_length=100, unique=True)),
                ('state', models.CharField(default='pending', max_length=12)),
                ('attempts', models.PositiveIntegerField(default=0)),
                ('retry_at', models.DateTimeField(null=True)),
                ('error_code', models.CharField(blank=True, max_length=40)),
                ('removed_at', models.DateTimeField(null=True)),
                ('size', models.PositiveBigIntegerField(default=0)),
            ],
        ),
    ]
