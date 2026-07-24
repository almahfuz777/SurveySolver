from django.db import transaction

from .models import ResponseAuditEvent, Submission


@transaction.atomic
def permanently_delete_submission(submission_id, user):
    submission = Submission.objects.select_for_update().select_related('survey', 'version').get(
        id=submission_id,
        survey__owner=user,
        status=Submission.Status.COMPLETED,
    )
    survey = submission.survey
    submission_uuid = submission.id
    metadata = {
        'version_id': str(submission.version_id),
        'version_number': submission.version.number,
        'source': submission.source,
        'completed_at': submission.completed_at.isoformat(),
    }
    ResponseAuditEvent.objects.create(
        survey=survey,
        submission_id=submission_uuid,
        actor=user,
        action=ResponseAuditEvent.Action.DELETED,
        metadata=metadata,
    )
    submission.delete()
    return survey, submission_uuid
