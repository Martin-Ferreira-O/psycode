
import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('capture', '0018_agentregistration_legacy_agent_id_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='AgentConfiguration',
            fields=[
                ('config_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('requested_by', models.UUIDField(null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('desired_config', models.JSONField(default=dict)),
                ('effective_config', models.JSONField(default=dict)),
                ('version', models.PositiveBigIntegerField()),
                ('state', models.CharField(choices=[('pendiente', 'Pending'), ('recibido', 'Received'), ('aplicado', 'Applied'), ('fallido', 'Failed')], default='pendiente', max_length=16)),
                ('error_code', models.CharField(blank=True, max_length=40)),
                ('agent', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='configurations', to='capture.agentregistration')),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('agent', 'version'), name='capture_unique_agent_config_version')],
            },
        ),
    ]
