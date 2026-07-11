import hashlib
import secrets
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from surveys.models import Survey

from .models import RespondentInvitation


INVITATION_LIFETIME = timedelta(days=7)
SESSION_KEY = 'respondent_invitation_grants'


def _hash_token(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


@transaction.atomic
def create_respondent_invitation(survey_id, user, email):
    survey = Survey.objects.select_for_update().get(id=survey_id, owner=user)
    if survey.status != Survey.Status.PUBLISHED:
        raise ValidationError('Publish this survey before inviting respondents.')
    email = email.strip().casefold()
    validate_email(email)
    RespondentInvitation.objects.filter(
        survey=survey,
        email=email,
        consumed_at__isnull=True,
        revoked_at__isnull=True,
    ).update(revoked_at=timezone.now())
    token = secrets.token_urlsafe(32)
    invitation = RespondentInvitation.objects.create(
        survey=survey,
        email=email,
        token_hash=_hash_token(token),
        created_by=user,
        expires_at=timezone.now() + INVITATION_LIFETIME,
    )
    return invitation, token


def deliver_respondent_invitation(invitation, invitation_url):
    context = {'invitation': invitation, 'invitation_url': invitation_url}
    message = EmailMultiAlternatives(
        subject=f'You are invited to take “{invitation.survey.title}”',
        body=render_to_string('sharing/email/respondent_invitation.txt', context),
        to=[invitation.email],
    )
    message.attach_alternative(
        render_to_string('sharing/email/respondent_invitation.html', context),
        'text/html',
    )
    try:
        sent = message.send(fail_silently=False)
    except Exception as error:
        RespondentInvitation.objects.filter(pk=invitation.pk).update(
            delivery_status=RespondentInvitation.DeliveryStatus.FAILED,
            delivery_error=f'{type(error).__name__}: email delivery failed'[:240],
        )
        return False
    RespondentInvitation.objects.filter(pk=invitation.pk).update(
        delivery_status=(
            RespondentInvitation.DeliveryStatus.SENT
            if sent
            else RespondentInvitation.DeliveryStatus.FAILED
        ),
        delivery_error='' if sent else 'Email backend reported no delivered messages.',
        sent_at=timezone.now() if sent else None,
    )
    return bool(sent)


def invitation_token_is_valid(invitation, token):
    return invitation.is_active and secrets.compare_digest(
        invitation.token_hash,
        _hash_token(token),
    )


def store_invitation_grant(session, invitation):
    grants = session.get(SESSION_KEY, {})
    grants[str(invitation.survey_id)] = str(invitation.id)
    session[SESSION_KEY] = grants
    session.modified = True


def invitation_from_session(session, survey, session_key):
    invitation_id = session.get(SESSION_KEY, {}).get(str(survey.id))
    if not invitation_id:
        return None
    invitation = RespondentInvitation.objects.filter(
        id=invitation_id,
        survey=survey,
    ).first()
    if invitation and invitation.is_active:
        return invitation
    if invitation and invitation.bound_submission_id:
        from responses.models import Submission
        from responses.services import hash_session_key

        if Submission.objects.filter(
            id=invitation.bound_submission_id,
            survey=survey,
            session_key_hash=hash_session_key(session_key),
        ).exists():
            return invitation
    grants = session.get(SESSION_KEY, {})
    grants.pop(str(survey.id), None)
    session[SESSION_KEY] = grants
    session.modified = True
    return None


def lock_respondent_invitation(invitation_id, survey_id):
    try:
        invitation = RespondentInvitation.objects.select_for_update().get(
            id=invitation_id,
            survey_id=survey_id,
        )
    except RespondentInvitation.DoesNotExist as error:
        raise PermissionDenied('This respondent invitation is unavailable.') from error
    if not invitation.is_active and invitation.consumed_at is None:
        raise PermissionDenied('This respondent invitation is unavailable.')
    return invitation


def bind_respondent_invitation(invitation, submission):
    if invitation.consumed_at is not None:
        if invitation.bound_submission_id != submission.id:
            raise PermissionDenied('This respondent invitation has already been used.')
        return invitation
    invitation.consumed_at = timezone.now()
    invitation.bound_submission_id = submission.id
    invitation.save(update_fields=('consumed_at', 'bound_submission_id'))
    return invitation


@transaction.atomic
def revoke_respondent_invitation(invitation_id, user):
    invitation = RespondentInvitation.objects.select_for_update().get(
        id=invitation_id,
        survey__owner=user,
    )
    if invitation.revoked_at is None and invitation.consumed_at is None:
        invitation.revoked_at = timezone.now()
        invitation.save(update_fields=('revoked_at',))
    return invitation
