
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('capture', '0004_fragmentjob_attempts_fragmentjob_finished_at_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='AgentStatus',
            fields=[
                ('box', models.CharField(max_length=16, primary_key=True, serialize=False)),
                ('seen_at', models.DateTimeField()),
                ('diagnostics', models.JSONField(default=dict)),
            ],
        ),
        migrations.CreateModel(
            name='RuntimeLease',
            fields=[
                ('name', models.CharField(max_length=100, primary_key=True, serialize=False)),
                ('owner', models.UUIDField()),
                ('expires_at', models.DateTimeField()),
            ],
        ),
    ]
