
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_user_role'),
    ]

    operations = [
        migrations.CreateModel(
            name='AuthRateLimit',
            fields=[
                ('key', models.CharField(max_length=64, primary_key=True, serialize=False)),
                ('expires_at', models.DateTimeField(db_index=True)),
                ('count', models.PositiveIntegerField(default=0)),
            ],
        ),
    ]
