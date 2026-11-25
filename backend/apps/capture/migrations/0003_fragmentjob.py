
import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('capture', '0002_allow_session_reauthorization'),
    ]

    operations = [
        migrations.CreateModel(
            name='FragmentJob',
            fields=[
                ('job_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('storage_key', models.CharField(max_length=37, unique=True)),
                ('checksum', models.CharField(max_length=64)),
                ('format', models.CharField(default='wav', max_length=8)),
                ('size', models.PositiveBigIntegerField()),
                ('state', models.CharField(choices=[('pendiente', 'Pending'), ('procesando', 'Processing'), ('completado', 'Completed'), ('fallido', 'Failed')], default='pendiente', max_length=16)),
                ('sequence', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='fragment_job', to='capture.acceptedsequence')),
            ],
            options={
                'indexes': [models.Index(fields=['state', 'job_id'], name='capture_pending_jobs')],
                'constraints': [models.CheckConstraint(condition=models.Q(('state__in', ['pendiente', 'procesando', 'completado', 'fallido'])), name='capture_valid_job_state'), models.CheckConstraint(condition=models.Q(('size__gt', 0)), name='capture_nonempty_fragment'), models.CheckConstraint(condition=models.Q(('format', 'wav')), name='capture_fragment_format')],
            },
        ),
    ]
