"""Survey rules: branching logic, response limits, targeting and collection state."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from ..models import (
    Survey,
    SurveyBranchRule,
    SurveyEligibilityCriteria,
    SurveyVersion,
)
from .drafting import (
    _bump_revision,
    _lock_version,
)


@transaction.atomic
def add_branch_rule(version_id, expected_revision, cleaned_data):
    version = _lock_version(version_id, expected_revision)
    source_question = cleaned_data.pop('source_question')
    target_section = cleaned_data.pop('target_section', None)
    compare_value = cleaned_data.get('compare_value', '')
    compare_choice = next(
        (
            choice
            for choice in source_question.choices.all()
            if choice.label == compare_value
        ),
        None,
    )
    order = (
        version.survey.presentation_branch_rules.aggregate(max_order=Max('order'))[
            'max_order'
        ]
        or 0
    ) + 1
    rule = SurveyBranchRule(
        survey=version.survey,
        source_question_identity=source_question.identity,
        target_section_identity=target_section.identity if target_section else None,
        compare_choice_identity=compare_choice.identity if compare_choice else None,
        order=order,
        **cleaned_data,
    )
    rule.full_clean()
    rule.save()
    return rule, _bump_revision(version)


@transaction.atomic
def delete_branch_rule(rule_id, expected_revision):
    rule = SurveyBranchRule.objects.select_related('survey').get(pk=rule_id)
    version = _lock_version(rule.survey.draft_version.id, expected_revision)
    rule.delete()
    return _bump_revision(version)


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


@transaction.atomic
def set_response_collection(survey_id, accepting):
    survey = Survey.objects.select_for_update().get(pk=survey_id)
    if survey.status not in {Survey.Status.PUBLISHED, Survey.Status.CLOSED}:
        raise ValidationError('Only published surveys can accept or pause responses.')
    if accepting and not survey.versions.filter(status=SurveyVersion.Status.PUBLISHED).exists():
        raise ValidationError('Publish a survey version before accepting responses.')

    target_status = Survey.Status.PUBLISHED if accepting else Survey.Status.CLOSED
    if survey.status == target_status:
        return survey

    survey.status = target_status
    survey.closed_at = None if accepting else timezone.now()
    survey.save(update_fields=('status', 'closed_at', 'updated_at'))
    return survey
