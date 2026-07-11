from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from sharing.permissions import VIEW_ROLES, get_accessible_survey
from surveys.models import SurveyVersion

from .services import PRIVACY_THRESHOLD, survey_analytics


@login_required
def survey_analytics_dashboard(request, survey_id):
    survey = get_accessible_survey(request.user, survey_id, VIEW_ROLES)
    versions = survey.versions.exclude(status=SurveyVersion.Status.DRAFT).order_by('-number')
    selected_version = None
    if request.GET.get('version'):
        selected_version = get_object_or_404(
            versions,
            id=request.GET['version'],
        )
    context = survey_analytics(survey, selected_version)
    context.update(
        {
            'survey': survey,
            'versions': versions,
            'selected_version': selected_version,
            'privacy_threshold': PRIVACY_THRESHOLD,
        }
    )
    return render(request, 'analytics/survey_dashboard.html', context)
