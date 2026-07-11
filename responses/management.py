from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import ResponseAuditEvent, Submission


@transaction.atomic
def set_analytics_exclusion(submission_id, user, *, excluded, reason=''):
    submission = Submission.objects.select_for_update().select_related('survey').get(
        id=submission_id,
        survey__owner=user,
        status=Submission.Status.COMPLETED,
    )
    reason = reason.strip()
    if len(reason) > 240:
        raise ValidationError('Exclusion reason must be 240 characters or fewer.')
    Submission.objects.filter(pk=submission.pk).update(
        is_excluded=excluded,
        exclusion_reason=reason if excluded else '',
        excluded_at=timezone.now() if excluded else None,
        excluded_by=user if excluded else None,
        updated_at=timezone.now(),
    )
    ResponseAuditEvent.objects.create(
        survey=submission.survey,
        submission_id=submission.id,
        actor=user,
        action=(
            ResponseAuditEvent.Action.EXCLUDED
            if excluded
            else ResponseAuditEvent.Action.INCLUDED
        ),
        metadata={'reason': reason} if excluded else {},
    )
    submission.refresh_from_db()
    return submission


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
        'was_excluded': submission.is_excluded,
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
