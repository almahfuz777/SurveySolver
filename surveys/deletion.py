from django.db import transaction

from responses.models import ResponseAuditEvent, Submission
from rewards.models import PointTransaction

from .models import Survey


@transaction.atomic
def permanently_delete_survey(survey_id, user):
    """Delete an owner's soft-deleted survey while retaining anonymous tombstones."""
    survey = Survey.objects.select_for_update().get(
        pk=survey_id,
        owner=user,
        deleted_at__isnull=False,
    )
    submissions = list(
        Submission.objects.select_for_update()
        .filter(survey=survey)
        .select_related('version')
    )
    ResponseAuditEvent.objects.bulk_create(
        [
            ResponseAuditEvent(
                survey=survey,
                submission_id=submission.id,
                actor=user,
                action=ResponseAuditEvent.Action.DELETED,
                metadata={
                    'version_id': str(submission.version_id),
                    'version_number': submission.version.number,
                    'source': submission.source,
                    'status': submission.status,
                    'completed_at': (
                        submission.completed_at.isoformat()
                        if submission.completed_at
                        else None
                    ),
                    'reason': 'survey_deleted',
                },
            )
            for submission in submissions
        ]
    )

    # Submission deletion invalidates guest claims and detaches immutable point
    # transactions from their response. The ledger and audit rows then lose
    # their final survey link before the survey-owned hierarchy is removed.
    Submission.objects.filter(survey=survey).delete()
    PointTransaction.objects.filter(survey=survey).update(survey=None)
    ResponseAuditEvent.objects.filter(survey=survey).update(survey=None)

    title = survey.title
    response_count = len(submissions)
    survey.delete()
    return title, response_count
