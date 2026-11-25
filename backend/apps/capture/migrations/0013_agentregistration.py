
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("capture", "0012_storagecleanuprun_provider_deleted_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="AgentRegistration",
            fields=[
                (
                    "agent_id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=100)),
                (
                    "box",
                    models.CharField(
                        choices=[
                            ("box-3", "Box 3"),
                            ("box-4", "Box 4"),
                            ("box-5", "Box 5"),
                            ("box-6", "Box 6"),
                            ("box-7", "Box 7"),
                        ],
                        max_length=16,
                    ),
                ),
                ("token_sha256", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
            ],
        ),
    ]
