"""Shared presentation work behind the builder views.

Nothing here writes to the database; draft mutations belong to surveys.services.
"""
from django.contrib import messages
from django.http import JsonResponse
from django.core.exceptions import ValidationError
from django.shortcuts import redirect

from ..branching import Action, Operator, allowed_operators
from ..models import Question
from ..presentation import resolved_version
from ..publication import branch_cycle_sections
from ..services import StaleVersionError


# Sentinel for `?question=` meaning "the creator deliberately selected nothing".
NO_SELECTION = 'none'

STALE_DRAFT_MESSAGE = 'This draft changed in another tab. Reload before continuing.'


def annotate_questions(version):
    """Attach presentation attributes (continuous number, scale points) to the
    prefetched question instances used by the responder-view templates."""
    sections = resolved_version(version)
    number = 0
    for section in sections:
        for question in section.questions.all():
            number += 1
            question.number = number
            if question.type == Question.Type.SCALE:
                scale_min = question.config.get('scale_min', 1)
                scale_max = question.config.get('scale_max', 5)
                question.scale_points = list(range(scale_min, scale_max + 1))[:20]
    return sections, number


def mutation_error(request, survey, error):
    if request.headers.get('Accept') == 'application/json':
        status = 409 if isinstance(error, StaleVersionError) else 422
        message = STALE_DRAFT_MESSAGE
        if isinstance(error, ValidationError):
            message = '; '.join(error.messages)
        return JsonResponse({'error': message}, status=status)
    if isinstance(error, StaleVersionError):
        messages.error(request, STALE_DRAFT_MESSAGE)
    else:
        messages.error(request, '; '.join(error.messages))
    return redirect('survey_builder', survey_id=survey.id)


def annotate_branch_warnings(version, question, rules):
    """Attach a `.warnings` list to each rule so the builder can flag conditions
    that can never match or that trap respondents in a loop, inline where the
    creator is setting them up."""
    if not rules:
        return
    cycle_sections = branch_cycle_sections(version)
    question_section_id = str(
        next(
            section.id
            for section in resolved_version(version)
            if section.identity_id == question.identity.section_identity_id
        )
    )
    allowed = set(allowed_operators(question.type))
    choice_labels = (
        {choice.label for choice in question.choices.all()}
        if question.accepts_choices
        else None
    )
    for rule in rules:
        warnings = []
        if rule.operator not in allowed:
            warnings.append(
                f'“{rule.get_operator_display()}” doesn’t apply to a {question.get_type_display()} '
                'question, so this rule can never match. Pick another condition.'
            )
        if (
            rule.action == Action.GO_TO_SECTION
            and question_section_id in cycle_sections
            and rule.target_section is not None
            and str(rule.target_section.id) in cycle_sections
        ):
            warnings.append(
                'This jump loops back to a section that leads here again — respondents could '
                'never finish. Send them to a later section or “End survey”.'
            )
        if (
            rule.action == Action.GO_TO_SECTION
            and rule.target_section is None
        ):
            warnings.append(
                'The target section is not part of this draft, so this rule is inactive.'
            )
        if (
            choice_labels is not None
            and rule.operator != Operator.ANSWERED
            and rule.compare_value
            and rule.compare_value not in choice_labels
        ):
            warnings.append(
                f'“{rule.compare_value}” is no longer one of this question’s options, '
                'so this rule will never trigger.'
            )
        rule.warnings = warnings
