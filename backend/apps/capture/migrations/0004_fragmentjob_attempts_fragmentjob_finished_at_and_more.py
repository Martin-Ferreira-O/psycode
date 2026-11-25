
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("capture", "0003_fragmentjob"),
    ]

    operations = [
        migrations.AddField(
            model_name="fragmentjob",
            name="attempts",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="fragmentjob",
            name="finished_at",
            field=models.DateTimeField(null=True),
        ),
        migrations.AddField(
            model_name="fragmentjob",
            name="last_error_code",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name="fragmentjob",
            name="processing_started_at",
            field=models.DateTimeField(null=True),
        ),
        migrations.AddField(
            model_name="fragmentjob",
            name="processing_token",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name="fragmentjob",
            name="result",
            field=models.CharField(
                blank=True,
                choices=[
                    ("riesgo_detectado", "Risk Detected"),
                    ("sin_riesgo_detectado", "No Risk Detected"),
                    ("indeterminado", "Indeterminate"),
                ],
                default="",
                max_length=24,
            ),
        ),
        migrations.AddIndex(
            model_name="fragmentjob",
            index=models.Index(
                fields=["state", "processing_started_at"], name="capture_job_recovery"
            ),
        ),
        migrations.AddConstraint(
            model_name="fragmentjob",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        "result__in",
                        [
                            "",
                            "riesgo_detectado",
                            "sin_riesgo_detectado",
                            "indeterminado",
                        ],
                    )
                ),
                name="capture_valid_job_result",
            ),
        ),
    ]
