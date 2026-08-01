from django.db import migrations, models


def simplify_profile_genders(apps, schema_editor):
    Profile = apps.get_model('accounts', 'Profile')
    Profile.objects.filter(
        gender__in=('non_binary', 'self_describe'),
    ).update(gender='other')
    Profile.objects.filter(gender='prefer_not_to_say').update(gender='')


def restore_legacy_profile_genders(apps, schema_editor):
    Profile = apps.get_model('accounts', 'Profile')
    Profile.objects.filter(gender='other').update(gender='non_binary')


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_alter_profile_research_interests'),
    ]

    operations = [
        migrations.RunPython(
            simplify_profile_genders,
            restore_legacy_profile_genders,
        ),
        migrations.RemoveField(
            model_name='profile',
            name='gender_self_description',
        ),
        migrations.AlterField(
            model_name='profile',
            name='gender',
            field=models.CharField(
                blank=True,
                choices=[
                    ('man', 'Man'),
                    ('woman', 'Woman'),
                    ('other', 'Other'),
                ],
                max_length=20,
            ),
        ),
    ]
