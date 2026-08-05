from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Section, SectionIdentity, Survey, SurveyVersion


@receiver(post_save, sender=Survey)
def create_initial_survey_version(sender, instance, created, **kwargs):
    if not created:
        return

    version = SurveyVersion.objects.create(
        survey=instance,
        number=1,
        created_by=instance.owner,
    )
    identity = SectionIdentity.objects.create(survey=instance, order=1)
    Section.objects.create(
        version=version,
        identity=identity,
        title='Section 1',
    )
