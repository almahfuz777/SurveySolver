from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Section, Survey, SurveyVersion


@receiver(post_save, sender=Survey)
def create_initial_survey_version(sender, instance, created, **kwargs):
    if not created:
        return

    version = SurveyVersion.objects.create(
        survey=instance,
        number=1,
        created_by=instance.owner,
    )
    Section.objects.create(version=version, title='Section 1', order=1)
