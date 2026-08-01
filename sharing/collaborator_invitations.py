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

from .models import CollaboratorInvitation, SurveyCollaborator
from .services import _grant_collaboration


INVITATION_LIFETIME = timedelta(days=7)


def _hash_token(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


@transaction.atomic
def create_collaborator_invitation(survey_id, user, email, role):
    survey = Survey.objects.select_for_update().get(id=survey_id, owner=user)
    email = email.strip().casefold()
    validate_email(email)
    if email == user.email.casefold():
        raise ValidationError('The survey owner already has full access.')
    if role not in SurveyCollaborator.Role.values:
        raise ValidationError('Select a valid collaboration role.')
    CollaboratorInvitation.objects.filter(
        survey=survey,
        email=email,
        accepted_at__isnull=True,
        revoked_at__isnull=True,
    ).update(revoked_at=timezone.now())
    token = secrets.token_urlsafe(32)
    invitation = CollaboratorInvitation.objects.create(
        survey=survey,
        email=email,
        role=role,
        token_hash=_hash_token(token),
        created_by=user,
        expires_at=timezone.now() + INVITATION_LIFETIME,
    )
    return invitation, token


def deliver_collaborator_invitation(invitation, invitation_url):
    context = {'invitation': invitation, 'invitation_url': invitation_url}
    message = EmailMultiAlternatives(
        subject=f'You are invited to collaborate on “{invitation.survey.title}”',
        body=render_to_string('sharing/email/collaborator_invitation.txt', context),
        to=[invitation.email],
    )
    message.attach_alternative(
        render_to_string('sharing/email/collaborator_invitation.html', context),
        'text/html',
    )
    try:
        sent = message.send(fail_silently=False)
    except Exception as error:
        CollaboratorInvitation.objects.filter(pk=invitation.pk).update(
            delivery_status=CollaboratorInvitation.DeliveryStatus.FAILED,
            delivery_error=f'{type(error).__name__}: email delivery failed'[:240],
        )
        return False
    CollaboratorInvitation.objects.filter(pk=invitation.pk).update(
        delivery_status=(
            CollaboratorInvitation.DeliveryStatus.SENT
            if sent
            else CollaboratorInvitation.DeliveryStatus.FAILED
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


@transaction.atomic
def accept_collaborator_invitation(invitation_id, token, user):
    invitation = (
        CollaboratorInvitation.objects.select_for_update()
        .select_related('survey', 'created_by')
        .get(id=invitation_id)
    )
    if not invitation_token_is_valid(invitation, token):
        raise PermissionDenied('This invitation is invalid or no longer active.')
    if user.email.casefold() != invitation.email:
        raise PermissionDenied('Sign in with the email address that received this invitation.')
    collaborator, created = _grant_collaboration(
        invitation.survey,
        user,
        invitation.role,
        invitation.created_by,
    )
    invitation.accepted_at = timezone.now()
    invitation.accepted_by = user
    invitation.save(update_fields=('accepted_at', 'accepted_by'))
    return collaborator, created


@transaction.atomic
def revoke_collaborator_invitation(invitation_id, user):
    invitation = CollaboratorInvitation.objects.select_for_update().get(
        id=invitation_id,
        survey__owner=user,
    )
    if invitation.revoked_at is None and invitation.accepted_at is None:
        invitation.revoked_at = timezone.now()
        invitation.save(update_fields=('revoked_at',))
    return invitation
