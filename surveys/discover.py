from django.db.models import Prefetch, Q
from django.utils import timezone

from .models import Survey, SurveyEligibilityCriteria, SurveyVersion


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
    # Single-value profile attributes: the respondent's value must be one of
    # the creator's allowed values (an unset criterion allows everyone).
    scalar_checks = (
        (criteria.education_levels, profile.education_level),
        (criteria.countries, profile.country.code if profile.country else ''),
        (criteria.regions, profile.region),
        (criteria.genders, profile.gender),
        (criteria.employment_statuses, profile.employment_status),
        (criteria.industries, profile.industry),
        (criteria.income_brackets, profile.income_bracket),
        (criteria.religions, profile.religion),
        (criteria.ethnicities, profile.ethnicity),
    )
    if not all(not allowed or value in allowed for allowed, value in scalar_checks):
        return False
    # Languages are multi-valued on the profile: match when they share at
    # least one language with the criteria.
    if criteria.languages:
        spoken = set(profile.languages or [])
        if spoken.isdisjoint(criteria.languages):
            return False
    return True


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
    completed_survey_ids = set()
    if user and user.is_authenticated:
        queryset = queryset.exclude(owner=user)
        completed_survey_ids = set(
            queryset.filter(
                submissions__respondent=user,
                submissions__status='completed',
            ).values_list('id', flat=True)
        )
        if not include_completed:
            queryset = queryset.exclude(id__in=completed_survey_ids)
    surveys = []
    for survey in queryset.distinct():
        if not survey.live_versions:
            continue
        survey.published_version = survey.live_versions[0]
        try:
            criteria = survey.eligibility_criteria
        except SurveyEligibilityCriteria.DoesNotExist:
            criteria = None
        survey.is_completed = survey.id in completed_survey_ids
        if not survey.is_completed and user and user.is_authenticated and not profile_matches(criteria, user.profile):
            continue
        survey.requires_screener = bool(
            criteria and criteria.is_targeted and not (user and user.is_authenticated)
        )
        surveys.append(survey)
    return surveys
