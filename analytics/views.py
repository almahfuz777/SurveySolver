from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse

from sharing.permissions import VIEW_ROLES, accessible_surveys, get_accessible_survey
from surveys.models import SurveyVersion

from .services import PRIVACY_THRESHOLD, survey_analytics


@login_required
def analytics_dashboard(request):
    surveys = list(
        accessible_surveys(request.user, VIEW_ROLES)
        .prefetch_related('versions')
        .order_by('title')
    )
    selected_survey = next(
        (survey for survey in surveys if str(survey.id) == request.GET.get('survey')),
        None,
    )
    if selected_survey is None:
        selected_survey = next(
            (
                survey
                for survey in surveys
                if any(
                    version.status != SurveyVersion.Status.DRAFT
                    for version in survey.versions.all()
                )
            ),
            surveys[0] if surveys else None,
        )

    versions = []
    selected_version = None
    context = {
        'surveys': surveys,
        'survey': selected_survey,
        'versions': versions,
        'selected_version': selected_version,
        'privacy_threshold': PRIVACY_THRESHOLD,
    }
    if selected_survey is not None:
        versions = sorted(
            (
                version
                for version in selected_survey.versions.all()
                if version.status != SurveyVersion.Status.DRAFT
            ),
            key=lambda version: version.number,
            reverse=True,
        )
        selected_version = next(
            (
                version
                for version in versions
                if str(version.id) == request.GET.get('version')
            ),
            None,
        )
        if selected_version is None:
            selected_version = next(
                (
                    version
                    for version in versions
                    if version.status == SurveyVersion.Status.PUBLISHED
                ),
                versions[0] if versions else None,
            )
        context.update(
            {
                'versions': versions,
                'selected_version': selected_version,
            }
        )
        if selected_version is not None:
            context.update(survey_analytics(selected_survey, selected_version))
    return render(request, 'analytics/survey_dashboard.html', context)


@login_required
def survey_analytics_dashboard(request, survey_id):
    survey = get_accessible_survey(request.user, survey_id, VIEW_ROLES)
    target = f"{reverse('analytics_dashboard')}?survey={survey.id}"
    if request.GET.get('version'):
        target += f"&version={request.GET['version']}"
    return redirect(target)
