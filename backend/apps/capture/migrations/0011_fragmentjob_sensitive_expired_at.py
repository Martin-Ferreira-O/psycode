
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('capture', '0010_storagecleanuprun_storagedeletion'),
    ]

    operations = [
        migrations.AddField(
            model_name='fragmentjob',
            name='sensitive_expired_at',
            field=models.DateTimeField(null=True),
        ),
    ]
