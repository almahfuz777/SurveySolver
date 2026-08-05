"""Persisting the survey settings a creator edits alongside the questionnaire.

Response limits and targeting live on the survey rather than the version, but editing them is a
draft change, so they take the same revision lock as a question edit.
"""
from django.db import transaction

from ..models import (
    Survey,
    SurveyEligibilityCriteria,
)
from .drafting import (
    _bump_revision,
    _lock_version,
)


@transaction.atomic
def update_response_limit(version_id, expected_revision, response_limit):
    version = _lock_version(version_id, expected_revision)
    Survey.objects.filter(pk=version.survey_id).update(response_limit=response_limit)
    return _bump_revision(version)


@transaction.atomic
def update_eligibility(version_id, expected_revision, cleaned_data):
    version = _lock_version(version_id, expected_revision)
    criteria_fields = (
        'min_age',
        'max_age',
        'education_levels',
        'countries',
        'regions',
        'genders',
        'employment_statuses',
        'industries',
        'income_brackets',
        'religions',
        'ethnicities',
        'languages',
    )
    defaults = {}
    for field in criteria_fields:
        default = None if field in ('min_age', 'max_age') else []
        defaults[field] = cleaned_data.get(field, default)
    criteria, _ = SurveyEligibilityCriteria.objects.update_or_create(
        survey=version.survey,
        defaults=defaults,
    )
    return criteria, _bump_revision(version)
