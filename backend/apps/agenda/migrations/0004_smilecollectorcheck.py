
import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agenda', '0003_room_legacy_transition'),
        ('capture', '0018_agentregistration_legacy_agent_id_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='SmileCollectorCheck',
            fields=[
                ('agent', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True, serialize=False, to='capture.agentregistration')),
                ('request_id', models.UUIDField(default=uuid.uuid4, unique=True)),
                ('source', models.CharField(max_length=64)),
                ('requested_at', models.DateTimeField()),
                ('expires_at', models.DateTimeField()),
                ('state', models.CharField(max_length=16)),
                ('result', models.CharField(blank=True, max_length=24)),
            ],
        ),
    ]
