
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('capture', '0011_fragmentjob_sensitive_expired_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='storagecleanuprun',
            name='provider_deleted',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='storagecleanuprun',
            name='provider_failures',
            field=models.PositiveIntegerField(default=0),
        ),
    ]
