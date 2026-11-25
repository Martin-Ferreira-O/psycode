
import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('capture', '0022_remote_configuration_revisions'),
        ('operational', '0006_jev_threshold'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='operationalconfiguration',
            name='operational_valid_speechmatics_model',
        ),
        migrations.AlterField(
            model_name='operationalconfiguration',
            name='speechmatics_model',
            field=models.CharField(default='enhanced', max_length=80, validators=[django.core.validators.RegexValidator('\\A[a-z0-9]+(?:[._-][a-z0-9]+)*\\Z')]),
        ),
        migrations.AddConstraint(
            model_name='operationalconfiguration',
            constraint=models.CheckConstraint(condition=models.Q(('speechmatics_model__regex', '\\A[a-z0-9]+(?:[._-][a-z0-9]+)*\\Z')), name='operational_valid_speechmatics_model_id'),
        ),
    ]
