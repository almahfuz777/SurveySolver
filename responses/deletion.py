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


def _record_bulk_deletion(survey, submissions, actor, reason):
    ResponseAuditEvent.objects.bulk_create(
        [
            ResponseAuditEvent(
                survey=survey,
                submission_id=submission.id,
                actor=actor,
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
                    'reason': reason,
                },
            )
            for submission in submissions
        ]
    )


@transaction.atomic
def purge_survey_responses(survey, actor):
    """Delete every response to a survey, leaving anonymous audit tombstones.

    Called when the survey itself is being removed, so the tombstones are
    detached from it rather than cascading away with it. Returns how many
    responses were deleted.
    """
    submissions = list(
        Submission.objects.select_for_update()
        .filter(survey=survey)
        .select_related('version')
    )
    _record_bulk_deletion(survey, submissions, actor, 'survey_deleted')
    Submission.objects.filter(survey=survey).delete()
    ResponseAuditEvent.objects.filter(survey=survey).update(survey=None)
    return len(submissions)


@transaction.atomic
def purge_version_responses(version, actor):
    """Delete every response captured by one version of a survey.

    The survey outlives the version, so unlike a full survey purge the audit
    tombstones stay attached to it. Returns how many responses were deleted.
    """
    submissions = list(
        Submission.objects.select_for_update()
        .filter(version=version)
        .select_related('version')
    )
    _record_bulk_deletion(version.survey, submissions, actor, 'retired_version_deleted')
    Submission.objects.filter(version=version).delete()
    return len(submissions)
