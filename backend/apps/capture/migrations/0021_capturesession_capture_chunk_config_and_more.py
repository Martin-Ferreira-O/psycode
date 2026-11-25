
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('capture', '0020_merge_audio_test_agent_configuration'),
    ]

    operations = [
        migrations.AddField(
            model_name='capturesession',
            name='capture_chunk_config',
            field=models.JSONField(default=dict, editable=False),
        ),
        migrations.AddField(
            model_name='capturesession',
            name='capture_chunk_negotiated',
            field=models.BooleanField(editable=False, null=True),
        ),
    ]
