"""Building the public survey catalogue."""
from django.db.models import Prefetch

from responses.services import completed_survey_ids
from surveys.models import Survey, SurveyEligibilityCriteria, SurveyVersion
from surveys.targeting import profile_matches


def discover_surveys(user=None, topics=None, duration=None, identity_mode=None, include_completed=False):
    published_versions = SurveyVersion.objects.filter(
        status=SurveyVersion.Status.PUBLISHED,
    )
    queryset = (
        Survey.objects.discoverable()
        .select_related('eligibility_criteria')
        .prefetch_related('topics', Prefetch('versions', published_versions, to_attr='live_versions'))
        .order_by('-published_at')
    )
    if topics:
        queryset = queryset.filter(topics__slug__in=topics)
    if duration:
        queryset = queryset.filter(estimated_minutes__lte=duration)
    if identity_mode:
        queryset = queryset.filter(identity_mode=identity_mode)
    completed_ids = set()
    if user and user.is_authenticated:
        queryset = queryset.exclude(owner=user)
        completed_ids = completed_survey_ids(user)
        if not include_completed:
            queryset = queryset.exclude(id__in=completed_ids)
    surveys = []
    for survey in queryset.distinct():
        if not survey.live_versions:
            continue
        survey.published_version = survey.live_versions[0]
        try:
            criteria = survey.eligibility_criteria
        except SurveyEligibilityCriteria.DoesNotExist:
            criteria = None
        survey.is_completed = survey.id in completed_ids
        if not survey.is_completed and user and user.is_authenticated and not profile_matches(criteria, user.profile):
            continue
        survey.requires_screener = bool(
            criteria and criteria.is_targeted and not (user and user.is_authenticated)
        )
        surveys.append(survey)
    return surveys
