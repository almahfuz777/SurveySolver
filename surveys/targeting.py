"""Matching a respondent's profile against a survey's eligibility criteria.

These rules interpret SurveyEligibilityCriteria, so they belong to the survey domain even though
the catalogue in the discover app is their only caller today.
"""
from django.utils import timezone


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
