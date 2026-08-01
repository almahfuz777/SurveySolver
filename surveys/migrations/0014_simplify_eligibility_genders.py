from django.db import migrations


LEGACY_OTHER_GENDERS = {'non_binary', 'self_describe'}


def _map_genders(values, *, reverse=False):
    mapped = []
    for value in values:
        if reverse:
            value = 'non_binary' if value == 'other' else value
        elif value in LEGACY_OTHER_GENDERS:
            value = 'other'
        elif value == 'prefer_not_to_say':
            continue
        if value not in mapped:
            mapped.append(value)
    return mapped


def simplify_eligibility_genders(apps, schema_editor):
    SurveyEligibilityCriteria = apps.get_model(
        'surveys',
        'SurveyEligibilityCriteria',
    )
    for criteria in SurveyEligibilityCriteria.objects.iterator():
        genders = _map_genders(criteria.genders)
        if genders != criteria.genders:
            SurveyEligibilityCriteria.objects.filter(pk=criteria.pk).update(
                genders=genders,
            )


def restore_legacy_eligibility_genders(apps, schema_editor):
    SurveyEligibilityCriteria = apps.get_model(
        'surveys',
        'SurveyEligibilityCriteria',
    )
    for criteria in SurveyEligibilityCriteria.objects.iterator():
        genders = _map_genders(criteria.genders, reverse=True)
        if genders != criteria.genders:
            SurveyEligibilityCriteria.objects.filter(pk=criteria.pk).update(
                genders=genders,
            )


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_simplify_profile_gender'),
        ('surveys', '0013_remove_eligibilitycriteria_version_and_more'),
    ]

    operations = [
        migrations.RunPython(
            simplify_eligibility_genders,
            restore_legacy_eligibility_genders,
        ),
    ]
