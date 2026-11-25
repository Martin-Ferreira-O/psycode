
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('capture', '0018_agentregistration_legacy_agent_id_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='capturesession',
            name='origin',
            field=models.CharField(choices=[('agenda', 'Agenda'), ('horario_clinico', 'Respaldo'), ('prueba_audio', 'Prueba de audio')], max_length=24),
        ),
        migrations.CreateModel(
            name='AudioTest',
            fields=[
                ('session', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, primary_key=True, serialize=False, to='capture.capturesession')),
                ('scenario', models.CharField(max_length=16)),
                ('samples', models.PositiveIntegerField()),
                ('expires_at', models.DateTimeField()),
                ('agent', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='capture.agentregistration')),
            ],
        ),
    ]
