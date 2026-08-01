"""Deciding whether a respondent may take a survey, and recording why."""
from datetime import date

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.core.validators import validate_email

from accounts.models import Profile
from django_countries import countries

from surveys.models import (
    Survey,
    SurveyEligibilityCriteria,
)

from ..models import Submission
from .errors import (
    EligibilityUnknown,
    IneligibleRespondent,
    QuotaReached,
    ResponseValidationError,
)


def _validated_identity(survey, consent, identity_data):
    if survey.identity_mode == Survey.IdentityMode.ANONYMOUS:
        return {}, None
    identity_data = identity_data or {}
    name = identity_data.get('name', '').strip()
    email = identity_data.get('email', '').strip().casefold()
    errors = {}
    if not consent:
        errors['identity_consent'] = 'Consent is required for an identified response.'
    if not name:
        errors['identity_name'] = 'Enter the name that will be shared with the researcher.'
    try:
        validate_email(email)
    except ValidationError:
        errors['identity_email'] = 'Enter a valid email address.'
    if errors:
        raise ResponseValidationError(errors)
    return {'name': name, 'email': email}, timezone.now()


def _current_age(birth_date):
    today = timezone.localdate()
    return today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )


def _eligibility_values(criteria, user, screener_data):
    targeted_fields = {
        'birth_date': criteria.min_age is not None or criteria.max_age is not None,
        'education_level': bool(criteria.education_levels),
        'country': bool(criteria.countries),
        'gender': bool(criteria.genders),
        'employment_status': bool(criteria.employment_statuses),
    }
    if user and user.is_authenticated:
        profile = user.profile
        values = {
            'birth_date': profile.birth_date,
            'education_level': profile.education_level,
            'country': profile.country.code if profile.country else '',
            'gender': profile.gender,
            'employment_status': profile.employment_status,
        }
        missing = [field for field, required in targeted_fields.items() if required and not values[field]]
        if missing:
            raise EligibilityUnknown('Complete the required research profile fields to continue.')
        return values

    screener_data = screener_data or {}
    values = {}
    errors = {}
    if targeted_fields['birth_date']:
        try:
            values['birth_date'] = date.fromisoformat(screener_data.get('birth_date', ''))
        except (TypeError, ValueError):
            errors['eligibility_birth_date'] = 'Enter a valid date of birth.'
    for field, allowed, error_message in (
        ('education_level', set(Profile.EducationLevel.values), 'Select your education level.'),
        ('gender', set(Profile.Gender.values), 'Select your gender.'),
        ('employment_status', set(Profile.EmploymentStatus.values), 'Select your employment status.'),
    ):
        if targeted_fields[field]:
            value = screener_data.get(field, '')
            if value not in allowed:
                errors[f'eligibility_{field}'] = error_message
            else:
                values[field] = value
    if targeted_fields['country']:
        value = screener_data.get('country', '')
        if value not in {code for code, _ in countries}:
            errors['eligibility_country'] = 'Select your country.'
        else:
            values['country'] = value
    if errors:
        raise ResponseValidationError(errors)
    return values


def _validated_eligibility(survey, user, screener_data):
    try:
        criteria = survey.eligibility_criteria
    except SurveyEligibilityCriteria.DoesNotExist:
        return {'targeted': False}, timezone.now()
    if not criteria.is_targeted:
        return {'targeted': False}, timezone.now()
    values = _eligibility_values(criteria, user, screener_data)
    age = _current_age(values['birth_date']) if values.get('birth_date') else None
    eligible = (
        (criteria.min_age is None or age >= criteria.min_age)
        and (criteria.max_age is None or age <= criteria.max_age)
        and (not criteria.education_levels or values['education_level'] in criteria.education_levels)
        and (not criteria.countries or values['country'] in criteria.countries)
        and (not criteria.genders or values['gender'] in criteria.genders)
        and (
            not criteria.employment_statuses
            or values['employment_status'] in criteria.employment_statuses
        )
    )
    if not eligible:
        raise IneligibleRespondent('Your screener does not match this study’s eligibility criteria.')
    snapshot = {
        key: value.isoformat() if isinstance(value, date) else value
        for key, value in values.items()
    }
    snapshot['targeted'] = True
    return snapshot, timezone.now()


def _ensure_quota_available(survey, version):
    if survey.response_limit is None:
        return
    completed = survey.submissions.filter(status=Submission.Status.COMPLETED).count()
    if completed >= survey.response_limit:
        raise QuotaReached('This survey has reached its response limit.')
