
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('capture', '0014_serverconnectivityoutage'),
    ]

    operations = [
        migrations.AddField(
            model_name='acceptedsequence',
            name='agent_id',
            field=models.CharField(blank=True, db_index=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='agentregistration',
            name='control_owner',
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name='agentregistration',
            name='diagnostics',
            field=models.JSONField(default=dict),
        ),
        migrations.AddField(
            model_name='agentregistration',
            name='last_seen_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
