import hashlib
import secrets
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from surveys.models import Survey

from .models import CollaborationLink, SurveyCollaborator


def _hash_token(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


@transaction.atomic
def create_collaboration_link(survey_id, user, role, lifetime_days=7):
    survey = Survey.objects.select_for_update().get(id=survey_id, owner=user)
    if role not in SurveyCollaborator.Role.values:
        raise ValidationError('Select a valid collaboration role.')
    if lifetime_days not in {1, 7, 30}:
        raise ValidationError('Select a supported expiration period.')
    token = secrets.token_urlsafe(32)
    link = CollaborationLink.objects.create(
        survey=survey,
        role=role,
        token_hash=_hash_token(token),
        created_by=user,
        expires_at=timezone.now() + timedelta(days=lifetime_days),
    )
    return link, token


def link_token_is_valid(link, token):
    return link.is_active and secrets.compare_digest(link.token_hash, _hash_token(token))


@transaction.atomic
def accept_collaboration_link(link_id, token, user):
    link = CollaborationLink.objects.select_for_update().select_related('survey').get(id=link_id)
    if not link_token_is_valid(link, token):
        raise PermissionDenied('This collaboration link is invalid or no longer active.')
    if link.survey.owner_id == user.id:
        return None, False
    existing = SurveyCollaborator.objects.filter(survey=link.survey, user=user).first()
    if existing:
        created = False
        if existing.role == SurveyCollaborator.Role.VIEWER and link.role == SurveyCollaborator.Role.EDITOR:
            existing.role = SurveyCollaborator.Role.EDITOR
            existing.added_by = link.created_by
            existing.save(update_fields=('role', 'added_by', 'updated_at'))
    else:
        existing = SurveyCollaborator.objects.create(
            survey=link.survey,
            user=user,
            role=link.role,
            added_by=link.created_by,
        )
        created = True
    CollaborationLink.objects.filter(pk=link.pk).update(
        accepted_count=F('accepted_count') + 1,
        last_accepted_at=timezone.now(),
    )
    return existing, created


@transaction.atomic
def revoke_collaboration_link(link_id, user):
    link = CollaborationLink.objects.select_for_update().get(id=link_id, survey__owner=user)
    if link.revoked_at is None:
        link.revoked_at = timezone.now()
        link.save(update_fields=('revoked_at',))
    return link


@transaction.atomic
def update_collaborator(collaborator_id, user, role):
    collaborator = SurveyCollaborator.objects.select_for_update().get(
        id=collaborator_id,
        survey__owner=user,
    )
    if role not in SurveyCollaborator.Role.values:
        raise ValidationError('Select a valid collaboration role.')
    collaborator.role = role
    collaborator.added_by = user
    collaborator.save(update_fields=('role', 'added_by', 'updated_at'))
    return collaborator


@transaction.atomic
def remove_collaborator(collaborator_id, user):
    collaborator = SurveyCollaborator.objects.select_for_update().get(
        id=collaborator_id,
        survey__owner=user,
    )
    collaborator.delete()
