from django.db import transaction

from responses.models import Submission
from sharing.models import SurveyCollaborator

from .models import PointTransaction


PROFILE_COMPLETION_BONUS = 50


@transaction.atomic
def award_profile_completion_bonus(profile):
    if not profile.is_complete:
        return None, False

    return PointTransaction.objects.get_or_create(
        idempotency_key=f'profile-completion:{profile.user_id}',
        defaults={
            'user': profile.user,
            'amount': PROFILE_COMPLETION_BONUS,
            'reason': PointTransaction.Reason.PROFILE_COMPLETION,
        },
    )


@transaction.atomic
def award_survey_completion(user, submission, points):
    submission = Submission.objects.select_for_update().select_related('survey', 'version').get(
        pk=submission.pk,
    )
    if (
        submission.status != Submission.Status.COMPLETED
        or not submission.is_eligible
        or user.id == submission.survey.owner_id
        or SurveyCollaborator.objects.filter(survey=submission.survey, user=user).exists()
        or (submission.respondent_id and submission.respondent_id != user.id)
    ):
        return None, False
    return PointTransaction.objects.get_or_create(
        user=user,
        survey=submission.survey,
        reason=PointTransaction.Reason.SURVEY_COMPLETION,
        defaults={
            'submission': submission,
            'amount': points,
            'idempotency_key': f'survey-completion:{user.id}:{submission.survey_id}',
            'metadata': {
                'submission_id': str(submission.id),
                'version_id': str(submission.version_id),
                'version_number': submission.version.number,
                'source': submission.source,
            },
        },
    )
