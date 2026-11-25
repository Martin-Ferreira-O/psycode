
import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("capture", "0013_agentregistration"),
    ]

    operations = [
        migrations.CreateModel(
            name="ServerConnectivityOutage",
            fields=[
                (
                    "outage_id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("box", models.CharField(max_length=16)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("detected_at", models.DateTimeField(auto_now_add=True)),
                ("recovered_at", models.DateTimeField(blank=True, null=True)),
                ("recovery_detected_at", models.DateTimeField(blank=True, null=True)),
                (
                    "start_time_quality",
                    models.CharField(
                        choices=[("estimated", "Estimado"), ("unknown", "Desconocido")],
                        default="unknown",
                        max_length=16,
                    ),
                ),
                (
                    "recovery_time_quality",
                    models.CharField(
                        choices=[("estimated", "Estimado"), ("unknown", "Desconocido")],
                        default="unknown",
                        max_length=16,
                    ),
                ),
                ("cause", models.CharField(default="UNKNOWN", max_length=40)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "agent",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="server_connectivity_outages",
                        to="capture.agentregistration",
                    ),
                ),
            ],
        ),
    ]
