from django.db import migrations


BADGES = (
    ('first-response', 'First Contribution', 'Completed your first rewarded research survey.', 1),
    ('five-responses', 'Research Helper', 'Completed five rewarded research surveys.', 5),
    ('twenty-five-responses', 'Insight Contributor', 'Completed 25 rewarded research surveys.', 25),
    ('one-hundred-responses', 'Research Champion', 'Completed 100 rewarded research surveys.', 100),
)


def seed_badges(apps, schema_editor):
    Badge = apps.get_model('rewards', 'Badge')
    for slug, name, description, threshold in BADGES:
        Badge.objects.update_or_create(
            slug=slug,
            defaults={
                'name': name,
                'description': description,
                'completion_threshold': threshold,
            },
        )


def remove_badges(apps, schema_editor):
    Badge = apps.get_model('rewards', 'Badge')
    Badge.objects.filter(slug__in=[badge[0] for badge in BADGES]).delete()


class Migration(migrations.Migration):
    dependencies = [('rewards', '0003_badge_badgeaward_pointtransaction_submission_and_more')]

    operations = [migrations.RunPython(seed_badges, remove_badges)]
