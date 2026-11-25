
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('capture', '0007_agentconnectivityevent_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='capturesession',
            name='capture_end_reason',
            field=models.CharField(blank=True, default='', max_length=40),
        ),
    ]
