
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('capture', '0008_capturesession_capture_end_reason'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='fragmentjob',
            name='capture_valid_job_state',
        ),
        migrations.AddField(
            model_name='fragmentjob',
            name='checkpoint',
            field=models.JSONField(default=dict),
        ),
        migrations.AddField(
            model_name='fragmentjob',
            name='retry_at',
            field=models.DateTimeField(null=True),
        ),
        migrations.AlterField(
            model_name='fragmentjob',
            name='state',
            field=models.CharField(choices=[('pendiente', 'Pending'), ('procesando', 'Processing'), ('completado', 'Completed'), ('fallido', 'Failed'), ('revision', 'Review')], default='pendiente', max_length=16),
        ),
        migrations.AddConstraint(
            model_name='fragmentjob',
            constraint=models.CheckConstraint(condition=models.Q(('state__in', ['pendiente', 'procesando', 'completado', 'fallido', 'revision'])), name='capture_valid_job_state'),
        ),
    ]
