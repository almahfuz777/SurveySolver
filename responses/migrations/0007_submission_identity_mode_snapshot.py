from django.db import migrations, models


def backfill_identity_mode(apps, schema_editor):
    Submission = apps.get_model('responses', 'Submission')
    Submission.objects.exclude(identity_data={}).update(
        identity_mode_snapshot='identified',
    )


class Migration(migrations.Migration):
    dependencies = [
        ('responses', '0006_upgrade_submission_presentations'),
    ]

    operations = [
        migrations.AddField(
            model_name='submission',
            name='identity_mode_snapshot',
            field=models.CharField(
                choices=[
                    ('anonymous', 'Anonymous to creator'),
                    ('identified', 'Identified with consent'),
                ],
                default='anonymous',
                max_length=16,
            ),
        ),
        migrations.RunPython(
            backfill_identity_mode,
            migrations.RunPython.noop,
        ),
    ]
