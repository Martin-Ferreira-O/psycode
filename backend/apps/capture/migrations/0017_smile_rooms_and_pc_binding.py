
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agenda', '0002_smile_rooms_and_pc_binding'),
        ('capture', '0016_pc_pairing_dynamic_rooms'),
    ]

    operations = [
        migrations.AddField(
            model_name='agentregistration',
            name='smile_room',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='pc', to='agenda.smileroom'),
        ),
    ]
