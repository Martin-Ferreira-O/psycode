from django.db import migrations, models


DEFAULT_URL = "https://192.168.10.184/providencia/usmile/index.php/"


def apply_smile_defaults(apps, schema_editor):
    config = apps.get_model("operational", "OperationalConfiguration")
    rows = config.objects.using(schema_editor.connection.alias)
    rows.filter(smile_collector__isnull=False).filter(
        ~models.Q(smile_timezone="America/Santiago") | models.Q(smile_url=""),
    ).update(smile_revision=models.F("smile_revision") + 1)
    rows.filter(smile_url="").update(smile_url=DEFAULT_URL)


class Migration(migrations.Migration):
    dependencies = [("operational", "0004_central_processing_and_smile")]

    operations = [
        migrations.RunPython(apply_smile_defaults, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="operationalconfiguration",
            name="smile_url",
            field=models.URLField(blank=True, default=DEFAULT_URL, max_length=2048),
        ),
        migrations.RemoveField(model_name="operationalconfiguration", name="smile_timezone"),
    ]
