
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('capture', '0006_capturesession_audio_profile_fragmentjob_temporal'),
    ]

    operations = [
        migrations.CreateModel(
            name='AgentConnectivityEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_id', models.UUIDField()),
                ('agent_id', models.CharField(max_length=64)),
                ('box', models.CharField(max_length=16)),
                ('session_id', models.UUIDField(null=True)),
                ('kind', models.CharField(max_length=40)),
                ('occurred_at', models.DateTimeField()),
                ('received_at', models.DateTimeField()),
                ('outage_id', models.UUIDField(null=True)),
                ('duration_ms', models.PositiveBigIntegerField(null=True)),
                ('cause', models.CharField(blank=True, max_length=40)),
            ],
        ),
        migrations.RemoveConstraint(
            model_name='capturesession',
            name='capture_one_open_session_per_box',
        ),
        migrations.AddField(
            model_name='capturesession',
            name='diagnostic_code',
            field=models.CharField(blank=True, default='', max_length=40),
        ),
        migrations.AddField(
            model_name='capturesession',
            name='reception_extended_until',
            field=models.DateTimeField(null=True),
        ),
        migrations.AddField(
            model_name='capturesession',
            name='reception_intervention_at',
            field=models.DateTimeField(null=True),
        ),
        migrations.AddConstraint(
            model_name='capturesession',
            constraint=models.UniqueConstraint(condition=models.Q(('actual_end__isnull', True), ('state__in', ('iniciada', 'activa', 'finalizando'))), fields=('box',), name='capture_one_open_session_per_box'),
        ),
        migrations.AddIndex(
            model_name='agentconnectivityevent',
            index=models.Index(fields=['box', 'occurred_at'], name='capture_agent_event_time'),
        ),
        migrations.AddConstraint(
            model_name='agentconnectivityevent',
            constraint=models.UniqueConstraint(fields=('agent_id', 'event_id'), name='capture_unique_agent_event'),
        ),
    ]
