"""Request-scoped lookups shared by the survey management and builder views."""
from django.shortcuts import get_object_or_404

from sharing.permissions import EDIT_ROLES, get_accessible_survey

from .models import SurveyVersion


def editable_survey(request, survey_id):
    return get_accessible_survey(request.user, survey_id, EDIT_ROLES)


def draft_version(survey):
    return get_object_or_404(
        SurveyVersion.objects.prefetch_related(
            'sections__questions__choices',
            'sections__questions__matrix_rows',
        ),
        survey=survey,
        status=SurveyVersion.Status.DRAFT,
    )


def posted_revision(request):
    try:
        return int(request.POST.get('revision', ''))
    except (TypeError, ValueError):
        return -1
