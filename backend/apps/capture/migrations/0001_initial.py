
import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='CaptureSession',
            fields=[
                ('session_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('box', models.CharField(max_length=16)),
                ('state', models.CharField(choices=[('iniciada', 'Started'), ('activa', 'Active'), ('finalizando', 'Stopping'), ('completada', 'Completed'), ('fallida', 'Failed')], max_length=16)),
                ('origin', models.CharField(choices=[('agenda', 'Agenda'), ('horario_clinico', 'Respaldo')], max_length=24)),
                ('scheduled_start', models.DateTimeField()),
                ('scheduled_end', models.DateTimeField()),
                ('authorized_at', models.DateTimeField()),
                ('actual_start', models.DateTimeField(null=True)),
                ('actual_end', models.DateTimeField(null=True)),
                ('stop_requested_at', models.DateTimeField(null=True)),
                ('closed_at', models.DateTimeField(null=True)),
                ('last_seen_at', models.DateTimeField()),
                ('next_sequence', models.PositiveBigIntegerField(default=0)),
                ('final_sequence', models.BigIntegerField(null=True)),
                ('error_code', models.CharField(blank=True, max_length=40)),
            ],
            options={
                'indexes': [models.Index(fields=['state', 'last_seen_at'], name='capture_cap_state_9d8ad1_idx')],
                'constraints': [models.UniqueConstraint(condition=models.Q(('state__in', ('iniciada', 'activa', 'finalizando'))), fields=('box',), name='capture_one_open_session_per_box'), models.UniqueConstraint(fields=('box', 'origin', 'scheduled_start', 'scheduled_end'), name='capture_one_session_per_window'), models.CheckConstraint(condition=models.Q(('scheduled_end__gt', models.F('scheduled_start'))), name='capture_valid_window'), models.CheckConstraint(condition=models.Q(('final_sequence__isnull', True), ('final_sequence__gte', -1), _connector='OR'), name='capture_valid_final_sequence'), models.CheckConstraint(condition=models.Q(('state__in', ['iniciada', 'activa', 'finalizando', 'completada', 'fallida'])), name='capture_valid_state'), models.CheckConstraint(condition=models.Q(('box__in', ['box-3', 'box-4', 'box-5', 'box-6', 'box-7'])), name='capture_valid_box')],
            },
        ),
        migrations.CreateModel(
            name='CaptureEvent',
            fields=[
                ('event_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('timestamp', models.DateTimeField()),
                ('action', models.CharField(max_length=40)),
                ('state', models.CharField(choices=[('iniciada', 'Started'), ('activa', 'Active'), ('finalizando', 'Stopping'), ('completada', 'Completed'), ('fallida', 'Failed')], max_length=16)),
                ('sequence', models.PositiveBigIntegerField(null=True)),
                ('command_id', models.UUIDField(null=True)),
                ('error_code', models.CharField(blank=True, max_length=40)),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='events', to='capture.capturesession')),
            ],
            options={
                'ordering': ['timestamp', 'event_id'],
            },
        ),
        migrations.CreateModel(
            name='AgentCommand',
            fields=[
                ('command_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('kind', models.CharField(choices=[('inicio', 'Start'), ('detencion', 'Stop')], max_length=12)),
                ('created_at', models.DateTimeField()),
                ('delivered_at', models.DateTimeField(null=True)),
                ('delivery_count', models.PositiveIntegerField(default=0)),
                ('acknowledged_at', models.DateTimeField(null=True)),
                ('succeeded', models.BooleanField(null=True)),
                ('occurred_at', models.DateTimeField(null=True)),
                ('last_sequence', models.BigIntegerField(null=True)),
                ('error_code', models.CharField(blank=True, max_length=40)),
                ('cancelled_at', models.DateTimeField(null=True)),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='commands', to='capture.capturesession')),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('session', 'kind'), name='capture_unique_session_command')],
            },
        ),
        migrations.CreateModel(
            name='AcceptedSequence',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('number', models.PositiveBigIntegerField()),
                ('captured_at', models.DateTimeField()),
                ('accepted_at', models.DateTimeField()),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='sequences', to='capture.capturesession')),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('session', 'number'), name='capture_unique_sequence')],
            },
        ),
    ]
