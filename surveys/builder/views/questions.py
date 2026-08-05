"""Adding, editing, reordering and removing the questions of a draft."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from ... import services
from ...models import Question, Section
from ...view_helpers import draft_version, editable_survey, posted_revision
from ..context import mutation_error
from ..forms import QuestionEditorForm


@require_POST
@login_required
def question_add(request, survey_id):
    survey = editable_survey(request, survey_id)
    section = get_object_or_404(Section, id=request.POST.get('section_id'), version__survey=survey)
    question_type = request.POST.get('type')
    if question_type not in Question.Type.values:
        return JsonResponse({'error': 'Invalid question type.'}, status=422)
    after_order = None
    after_id = request.POST.get('after_question_id')
    if after_id:
        after = Question.objects.filter(
            id=after_id,
            section__version=section.version,
        ).values_list('identity__order', flat=True).first()
        if after is not None:
            after_order = after
    try:
        question, _ = services.add_question(section.id, question_type, posted_revision(request), after_order)
    except (services.StaleVersionError, ValidationError) as error:
        return mutation_error(request, survey, error)
    return redirect(f"{reverse('survey_builder', args=[survey.id])}?question={question.id}")


@require_POST
@login_required
def question_duplicate(request, survey_id, question_id):
    survey = editable_survey(request, survey_id)
    question = get_object_or_404(Question, id=question_id, section__version__survey=survey)
    try:
        clone, _ = services.duplicate_question(question.id, posted_revision(request))
    except (services.StaleVersionError, ValidationError) as error:
        return mutation_error(request, survey, error)
    return redirect(f"{reverse('survey_builder', args=[survey.id])}?question={clone.id}")


@require_POST
@login_required
def question_reorder(request, survey_id, question_id):
    survey = editable_survey(request, survey_id)
    version = draft_version(survey)
    question = get_object_or_404(Question, id=question_id, section__version=version)
    section = get_object_or_404(Section, id=request.POST.get('section_id'), version=version)
    try:
        position = int(request.POST.get('position', ''))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Invalid position.'}, status=422)
    try:
        services.reorder_question(question.id, posted_revision(request), section.id, position)
    except (services.StaleVersionError, ValidationError) as error:
        return mutation_error(request, survey, error)
    return redirect(f"{reverse('survey_builder', args=[survey.id])}?question={question.id}")


@require_POST
@login_required
def question_update(request, survey_id, question_id):
    survey = editable_survey(request, survey_id)
    question = get_object_or_404(Question, id=question_id, section__version__survey=survey)
    form = QuestionEditorForm(request.POST, instance=question)
    if not form.is_valid():
        return JsonResponse({'errors': form.errors.get_json_data()}, status=422)
    try:
        _, revision = services.update_question(
            question.id,
            posted_revision(request),
            form.cleaned_data,
            form.question_config(),
            form.cleaned_data['choice_labels'],
            form.cleaned_data['row_labels'],
            form.cleaned_data['choice_identity_ids'],
            form.cleaned_data['row_identity_ids'],
        )
    except (services.StaleVersionError, ValidationError) as error:
        return mutation_error(request, survey, error)
    return JsonResponse({'revision': revision})


@require_POST
@login_required
def question_move(request, survey_id, question_id):
    survey = editable_survey(request, survey_id)
    question = get_object_or_404(Question, id=question_id, section__version__survey=survey)
    direction = request.POST.get('direction')
    if direction not in {'up', 'down'}:
        return JsonResponse({'error': 'Invalid direction.'}, status=422)
    try:
        services.move_question(question.id, posted_revision(request), direction)
    except (services.StaleVersionError, ValidationError) as error:
        return mutation_error(request, survey, error)
    return redirect(f"{reverse('survey_builder', args=[survey.id])}?question={question.id}")


@require_POST
@login_required
def question_delete(request, survey_id, question_id):
    survey = editable_survey(request, survey_id)
    question = get_object_or_404(Question, id=question_id, section__version__survey=survey)
    try:
        services.delete_question(question.id, posted_revision(request))
    except (services.StaleVersionError, ValidationError) as error:
        return mutation_error(request, survey, error)
    return redirect('survey_builder', survey_id=survey.id)
