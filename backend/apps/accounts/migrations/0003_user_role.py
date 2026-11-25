
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_passwordresetratelimit"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[("admin", "Administrador"), ("supervisor", "Supervisor")],
                default="supervisor",
                help_text="Rol del usuario en el sistema",
                max_length=20,
            ),
        ),
    ]
