"""Authoring the branching rules that route a respondent through a questionnaire."""
from django.db import transaction
from django.db.models import Max

from ..models import SurveyBranchRule
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
