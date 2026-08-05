"""Attaching branching logic to a question in the draft."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from ... import services
from ...models import Question, SurveyBranchRule
from ...view_helpers import draft_version, editable_survey, posted_revision
from ..context import mutation_error
from ..forms import QuestionBranchForm


@require_POST
@login_required
def question_branch_add(request, survey_id, question_id):
    survey = editable_survey(request, survey_id)
    version = draft_version(survey)
    question = get_object_or_404(Question, id=question_id, section__version=version)
    form = QuestionBranchForm(request.POST, version=version, question=question)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect(f"{reverse('survey_builder', args=[survey.id])}?question={question.id}")
    try:
        services.add_branch_rule(
            version.id,
            posted_revision(request),
            {'source_question': question, **form.cleaned_data},
        )
    except (services.StaleVersionError, ValidationError) as error:
        return mutation_error(request, survey, error)
    messages.success(request, 'Logic rule added.')
    return redirect(f"{reverse('survey_builder', args=[survey.id])}?question={question.id}")


@require_POST
@login_required
def question_branch_delete(request, survey_id, rule_id):
    survey = editable_survey(request, survey_id)
    rule = get_object_or_404(SurveyBranchRule, id=rule_id, survey=survey)
    question = get_object_or_404(
        Question,
        section__version=survey.draft_version,
        identity=rule.source_question_identity,
    )
    question_id = question.id
    try:
        services.delete_branch_rule(rule.id, posted_revision(request))
    except (services.StaleVersionError, ValidationError) as error:
        return mutation_error(request, survey, error)
    messages.success(request, 'Logic rule removed.')
    return redirect(f"{reverse('survey_builder', args=[survey.id])}?question={question_id}")
