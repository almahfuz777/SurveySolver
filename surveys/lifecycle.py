"""Survey state transitions that happen outside the draft.

Opening and closing a survey to responses changes what respondents see immediately, so it takes no
revision lock and never touches the draft version.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Survey, SurveyVersion


@transaction.atomic
def set_response_collection(survey_id, accepting):
    survey = Survey.objects.select_for_update().get(pk=survey_id)
    if survey.status not in {Survey.Status.PUBLISHED, Survey.Status.CLOSED}:
        raise ValidationError('Only published surveys can accept or pause responses.')
    if accepting and not survey.versions.filter(status=SurveyVersion.Status.PUBLISHED).exists():
        raise ValidationError('Publish a survey version before accepting responses.')

    target_status = Survey.Status.PUBLISHED if accepting else Survey.Status.CLOSED
    if survey.status == target_status:
        return survey

    survey.status = target_status
    survey.closed_at = None if accepting else timezone.now()
    survey.save(update_fields=('status', 'closed_at', 'updated_at'))
    return survey
