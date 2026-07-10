from django.db.models import Prefetch, Q
from django.utils import timezone

from .models import EligibilityCriteria, Survey, SurveyVersion


def _age_on(birth_date):
    today = timezone.localdate()
    return today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )


def profile_matches(criteria, profile):
    if not criteria or not criteria.is_targeted:
        return True
    if criteria.min_age is not None or criteria.max_age is not None:
        if not profile.birth_date:
            return False
        age = _age_on(profile.birth_date)
        if criteria.min_age is not None and age < criteria.min_age:
            return False
        if criteria.max_age is not None and age > criteria.max_age:
            return False
    values = (
        (criteria.education_levels, profile.education_level),
        (criteria.countries, profile.country.code if profile.country else ''),
        (criteria.genders, profile.gender),
        (criteria.employment_statuses, profile.employment_status),
    )
    return all(not allowed or value in allowed for allowed, value in values)


def discover_surveys(user=None, topic=None, duration=None):
    published_versions = SurveyVersion.objects.filter(
        status=SurveyVersion.Status.PUBLISHED,
    ).select_related('eligibility_criteria')
    queryset = (
        Survey.objects.discoverable()
        .prefetch_related('topics', Prefetch('versions', published_versions, to_attr='live_versions'))
        .order_by('-published_at')
    )
    if topic:
        queryset = queryset.filter(topics__slug=topic)
    if duration:
        queryset = queryset.filter(estimated_minutes__lte=duration)
    if user and user.is_authenticated:
        queryset = queryset.exclude(
            Q(owner=user)
            | Q(
                submissions__respondent=user,
                submissions__status='completed',
            )
        )
    surveys = []
    for survey in queryset.distinct():
        if not survey.live_versions:
            continue
        survey.published_version = survey.live_versions[0]
        try:
            criteria = survey.published_version.eligibility_criteria
        except EligibilityCriteria.DoesNotExist:
            criteria = None
        if user and user.is_authenticated and not profile_matches(criteria, user.profile):
            continue
        survey.requires_screener = bool(
            criteria and criteria.is_targeted and not (user and user.is_authenticated)
        )
        surveys.append(survey)
    return surveys
