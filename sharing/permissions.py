from django.db.models import Q
from django.shortcuts import get_object_or_404

from surveys.models import Survey

from .models import SurveyCollaborator


OWNER = 'owner'
EDITOR = SurveyCollaborator.Role.EDITOR
VIEWER = SurveyCollaborator.Role.VIEWER
VIEW_ROLES = (OWNER, EDITOR, VIEWER)
EDIT_ROLES = (OWNER, EDITOR)
OWNER_ROLES = (OWNER,)


def role_for(user, survey):
    if not user or not user.is_authenticated:
        return None
    if survey.owner_id == user.id:
        return OWNER
    return (
        SurveyCollaborator.objects.filter(survey=survey, user=user)
        .values_list('role', flat=True)
        .first()
    )


def accessible_surveys(user, roles=VIEW_ROLES):
    if not user or not user.is_authenticated or not roles:
        return Survey.objects.none()
    query = Q()
    if OWNER in roles:
        query |= Q(owner=user)
    collaboration_roles = [role for role in roles if role != OWNER]
    if collaboration_roles:
        query |= Q(collaborators__user=user, collaborators__role__in=collaboration_roles)
    return Survey.objects.filter(query)


def get_accessible_survey(user, survey_id, roles=VIEW_ROLES):
    survey = get_object_or_404(accessible_surveys(user, roles), id=survey_id)
    survey.access_role = role_for(user, survey)
    return survey
