from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("capture", "0021_capturesession_capture_chunk_config_and_more")]
    operations = [
        migrations.AddField(model_name="agentconfiguration", name="source",
            field=models.CharField(max_length=8, default="remote", choices=[("remote", "Web"), ("local", "Local")])),
        migrations.AddField(model_name="agentconfiguration", name="local_revision",
            field=models.PositiveBigIntegerField(default=0)),
    ]
