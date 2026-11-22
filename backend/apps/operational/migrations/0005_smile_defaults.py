from django.conf import settings
from django.db import migrations, models


def apply_smile_defaults(apps, schema_editor):
    config = apps.get_model("operational", "OperationalConfiguration")
    rows = config.objects.using(schema_editor.connection.alias)
    default_url = settings.SMILE_DEFAULT_URL
    changed = ~models.Q(smile_timezone="America/Santiago")
    if default_url:
        changed |= models.Q(smile_url="")
    rows.filter(smile_collector__isnull=False).filter(changed).update(
        smile_revision=models.F("smile_revision") + 1,
    )
    if default_url:
        rows.filter(smile_url="").update(smile_url=default_url)


class Migration(migrations.Migration):
    dependencies = [("operational", "0004_central_processing_and_smile")]

    operations = [
        migrations.RunPython(apply_smile_defaults, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="operationalconfiguration",
            name="smile_url",
            field=models.URLField(blank=True, default="", max_length=2048),
        ),
        migrations.RemoveField(model_name="operationalconfiguration", name="smile_timezone"),
    ]
