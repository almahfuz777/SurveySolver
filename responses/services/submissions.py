"""Starting, resuming and abandoning a response."""

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q


from surveys.models import (
    Survey,
    SurveyVersion,
)

from ..models import Submission
from .eligibility import (
    _ensure_account_access,
    _ensure_quota_available,
    _validated_eligibility,
    _validated_identity,
)
from .sessions import build_presentation, current_published_version, hash_session_key


@transaction.atomic
def start_submission(
    survey,
    user,
    session_key,
    source=Submission.Source.DIRECT,
    identity_consent=False,
    screener_data=None,
    respondent_invitation_id=None,
):
    from sharing.respondent_invitations import (
        bind_respondent_invitation,
        lock_respondent_invitation,
    )

    survey = Survey.objects.select_for_update().get(pk=survey.pk)
    invitation = None
    if respondent_invitation_id:
        invitation = lock_respondent_invitation(respondent_invitation_id, survey.id)
    version = current_published_version(survey, invitation_access=bool(invitation))
    session_hash = hash_session_key(session_key)
    respondent = user if user and user.is_authenticated else None
    # Before any existing draft is handed back, so flipping the setting locks guests out at once.
    _ensure_account_access(survey, user)
    if invitation and invitation.bound_submission_id:
        bound_submission = Submission.objects.filter(
            id=invitation.bound_submission_id,
            survey=survey,
        ).first()
        if bound_submission and can_access_submission(bound_submission, user, session_key):
            return bound_submission
        raise PermissionDenied('This respondent invitation has already been used.')
    in_progress_filter = Q(session_key_hash=session_hash)
    if respondent:
        in_progress_filter |= Q(respondent=respondent)
    existing = Submission.objects.filter(
        in_progress_filter,
        survey=survey,
        version=version,
        status=Submission.Status.IN_PROGRESS,
    ).first()
    if existing:
        if invitation:
            if existing.source != Submission.Source.INVITATION:
                existing.source = Submission.Source.INVITATION
                existing.save(update_fields=('source', 'updated_at'))
            bind_respondent_invitation(invitation, existing)
        return existing
    completed_filter = Q(session_key_hash=session_hash)
    if respondent:
        completed_filter |= Q(respondent=respondent)
    completed = Submission.objects.filter(
        completed_filter,
        survey=survey,
        status=Submission.Status.COMPLETED,
    ).first()
    if completed:
        return completed
    _ensure_quota_available(survey, version)
    eligibility_data, eligibility_checked_at = _validated_eligibility(
        survey,
        respondent,
        screener_data,
    )
    identity_data, identity_consent_at = _validated_identity(survey, respondent, identity_consent)
    submission = Submission.objects.create(
        survey=survey,
        version=version,
        respondent=respondent,
        session_key_hash=session_hash,
        source=(Submission.Source.INVITATION if invitation else source),
        presentation=build_presentation(version),
        identity_mode_snapshot=survey.identity_mode,
        identity_data=identity_data,
        identity_consent_at=identity_consent_at,
        is_eligible=True,
        eligibility_data=eligibility_data,
        eligibility_checked_at=eligibility_checked_at,
    )
    SurveyVersion.objects.filter(pk=version.pk, has_response_history=False).update(
        has_response_history=True,
    )
    if invitation:
        bind_respondent_invitation(invitation, submission)
    return submission


def can_access_submission(submission, user, session_key):
    if submission.session_key_hash == hash_session_key(session_key):
        return True
    return bool(
        user
        and user.is_authenticated
        and submission.respondent_id
        and submission.respondent_id == user.id
    )


def completed_survey_ids(user):
    """The ids of every survey this user has completed a response to."""
    if not (user and user.is_authenticated):
        return set()
    return set(
        Submission.objects.filter(
            respondent=user,
            status=Submission.Status.COMPLETED,
        ).values_list('survey_id', flat=True)
    )


def completed_response_counts(surveys):
    """How many completed responses each of these surveys has, keyed by survey id."""
    return dict(
        Submission.objects.filter(
            survey__in=surveys,
            status=Submission.Status.COMPLETED,
        )
        .values_list('survey')
        .annotate(total=Count('id'))
    )


def resumable_submissions(user, session_key):
    access_filters = []
    if session_key:
        access_filters.append(
            Q(session_key_hash=hash_session_key(session_key)),
        )
    if user and user.is_authenticated:
        access_filters.append(Q(respondent=user))
    if not access_filters:
        return Submission.objects.none()

    access_filter = access_filters[0]
    for condition in access_filters[1:]:
        access_filter |= condition
    queryset = Submission.objects.filter(
        access_filter,
        status=Submission.Status.IN_PROGRESS,
        survey__deleted_at__isnull=True,
    )
    if not (user and user.is_authenticated):
        # A guest draft on a survey that has since become account-only is no longer resumable.
        queryset = queryset.filter(survey__in=Survey.objects.answerable_by_guests())
    return (
        queryset
        .select_related('survey', 'version')
        .prefetch_related('survey__topics')
        .annotate(saved_answer_count=Count('answers', distinct=True))
        .order_by('-updated_at')
        .distinct()
    )


@transaction.atomic
def discard_in_progress_submission(submission_id, user, session_key):
    submission = (
        Submission.objects.select_for_update()
        .select_related('survey')
        .get(
            pk=submission_id,
            status=Submission.Status.IN_PROGRESS,
        )
    )
    if not can_access_submission(submission, user, session_key):
        raise PermissionDenied
    survey_title = submission.survey.title
    submission.delete()
    return survey_title
