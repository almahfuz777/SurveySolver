from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import services
from .forms import BranchRuleForm, QuestionEditorForm, QuotaForm, SectionForm, SurveyMetadataForm
from .models import Question, Section, Survey, SurveyVersion


@login_required
def survey_list(request):
    surveys = Survey.objects.owned_by(request.user).prefetch_related('topics')
    return render(request, 'surveys/survey_list.html', {'surveys': surveys})


@login_required
def survey_create(request):
    if request.method == 'POST':
        form = SurveyMetadataForm(request.POST, request.FILES)
        if form.is_valid():
            survey = form.save(commit=False)
            survey.owner = request.user
            survey.save()
            form.save_m2m()
            messages.success(request, 'Survey draft created. Add questions when you are ready.')
            return redirect('survey_detail', survey_id=survey.id)
    else:
        form = SurveyMetadataForm()

    return render(
        request,
        'surveys/survey_form.html',
        {'form': form, 'page_title': 'Create a research survey'},
    )


@login_required
def survey_detail(request, survey_id):
    survey = get_object_or_404(
        Survey.objects.prefetch_related('topics'),
        id=survey_id,
        owner=request.user,
    )
    return render(
        request,
        'surveys/survey_detail.html',
        {'survey': survey, 'draft_version': survey.draft_version},
    )


@login_required
def survey_edit(request, survey_id):
    survey = get_object_or_404(Survey, id=survey_id, owner=request.user)
    if request.method == 'POST':
        form = SurveyMetadataForm(request.POST, request.FILES, instance=survey)
        if form.is_valid():
            form.save()
            messages.success(request, 'Survey details updated.')
            return redirect('survey_detail', survey_id=survey.id)
    else:
        form = SurveyMetadataForm(instance=survey)

    return render(
        request,
        'surveys/survey_form.html',
        {'form': form, 'survey': survey, 'page_title': 'Edit survey details'},
    )


@require_POST
@login_required
def survey_archive(request, survey_id):
    survey = get_object_or_404(Survey, id=survey_id, owner=request.user)
    survey.archive()
    messages.success(request, 'Survey archived.')
    return redirect('survey_list')


def _owned_survey(request, survey_id):
    return get_object_or_404(Survey, id=survey_id, owner=request.user)


def _draft_version(survey):
    return get_object_or_404(
        SurveyVersion.objects.prefetch_related('sections__questions__choices'),
        survey=survey,
        status=SurveyVersion.Status.DRAFT,
    )


def _revision(request):
    try:
        return int(request.POST.get('revision', ''))
    except (TypeError, ValueError):
        return -1


def _mutation_error(request, survey, error):
    if request.headers.get('Accept') == 'application/json':
        status = 409 if isinstance(error, services.StaleVersionError) else 422
        message = 'This draft changed in another tab. Reload before continuing.'
        if isinstance(error, ValidationError):
            message = '; '.join(error.messages)
        return JsonResponse({'error': message}, status=status)
    if isinstance(error, services.StaleVersionError):
        messages.error(request, 'This draft changed in another tab. Reload before continuing.')
    else:
        messages.error(request, '; '.join(error.messages))
    return redirect('survey_builder', survey_id=survey.id)


@login_required
def survey_builder(request, survey_id):
    survey = _owned_survey(request, survey_id)
    version = _draft_version(survey)
    selected_question = None
    selected_id = request.GET.get('question')
    if selected_id:
        selected_question = get_object_or_404(
            Question.objects.prefetch_related('choices'),
            id=selected_id,
            section__version=version,
        )
    if selected_question is None:
        selected_question = (
            Question.objects.filter(section__version=version)
            .prefetch_related('choices')
            .order_by('section__order', 'order')
            .first()
        )
    editor_form = QuestionEditorForm(instance=selected_question) if selected_question else None
    return render(
        request,
        'surveys/builder.html',
        {
            'survey': survey,
            'version': version,
            'question_types': Question.Type.choices,
            'selected_question': selected_question,
            'editor_form': editor_form,
        },
    )


@login_required
def survey_preview(request, survey_id):
    survey = _owned_survey(request, survey_id)
    version = _draft_version(survey)
    return render(request, 'surveys/preview.html', {'survey': survey, 'version': version})


@login_required
def survey_logic(request, survey_id):
    survey = _owned_survey(request, survey_id)
    version = _draft_version(survey)
    branch_form = BranchRuleForm(version=version)
    quota_form = QuotaForm()
    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            if action == 'add_branch':
                branch_form = BranchRuleForm(request.POST, version=version)
                if branch_form.is_valid():
                    services.add_branch_rule(version.id, _revision(request), branch_form.cleaned_data)
                    messages.success(request, 'Branch rule added.')
                    return redirect('survey_logic', survey_id=survey.id)
            elif action == 'add_quota':
                quota_form = QuotaForm(request.POST)
                if quota_form.is_valid():
                    services.add_quota(version.id, _revision(request), quota_form.cleaned_data)
                    messages.success(request, 'Quota added.')
                    return redirect('survey_logic', survey_id=survey.id)
        except (services.StaleVersionError, ValidationError) as error:
            return _mutation_error(request, survey, error)
    return render(request, 'surveys/logic.html', {'survey': survey, 'version': version, 'branch_form': branch_form, 'quota_form': quota_form})


@require_POST
@login_required
def section_add(request, survey_id):
    survey = _owned_survey(request, survey_id)
    version = _draft_version(survey)
    try:
        services.add_section(version.id, _revision(request))
    except (services.StaleVersionError, ValidationError) as error:
        return _mutation_error(request, survey, error)
    return redirect('survey_builder', survey_id=survey.id)


@require_POST
@login_required
def section_update(request, survey_id, section_id):
    survey = _owned_survey(request, survey_id)
    section = get_object_or_404(Section, id=section_id, version__survey=survey)
    form = SectionForm(request.POST, instance=section)
    if not form.is_valid():
        return JsonResponse({'errors': form.errors.get_json_data()}, status=422)
    try:
        _, revision = services.update_section(section.id, _revision(request), form.cleaned_data)
    except (services.StaleVersionError, ValidationError) as error:
        return _mutation_error(request, survey, error)
    return JsonResponse({'revision': revision})


@require_POST
@login_required
def section_move(request, survey_id, section_id):
    survey = _owned_survey(request, survey_id)
    section = get_object_or_404(Section, id=section_id, version__survey=survey)
    direction = request.POST.get('direction')
    if direction not in {'up', 'down'}:
        return JsonResponse({'error': 'Invalid direction.'}, status=422)
    try:
        services.move_section(section.id, _revision(request), direction)
    except (services.StaleVersionError, ValidationError) as error:
        return _mutation_error(request, survey, error)
    return redirect('survey_builder', survey_id=survey.id)


@require_POST
@login_required
def section_delete(request, survey_id, section_id):
    survey = _owned_survey(request, survey_id)
    section = get_object_or_404(Section, id=section_id, version__survey=survey)
    try:
        services.delete_section(section.id, _revision(request))
    except (services.StaleVersionError, ValidationError) as error:
        return _mutation_error(request, survey, error)
    return redirect('survey_builder', survey_id=survey.id)


@require_POST
@login_required
def question_add(request, survey_id):
    survey = _owned_survey(request, survey_id)
    section = get_object_or_404(Section, id=request.POST.get('section_id'), version__survey=survey)
    question_type = request.POST.get('type')
    if question_type not in Question.Type.values:
        return JsonResponse({'error': 'Invalid question type.'}, status=422)
    try:
        question, _ = services.add_question(section.id, question_type, _revision(request))
    except (services.StaleVersionError, ValidationError) as error:
        return _mutation_error(request, survey, error)
    return redirect(f"{reverse('survey_builder', args=[survey.id])}?question={question.id}")


@require_POST
@login_required
def question_update(request, survey_id, question_id):
    survey = _owned_survey(request, survey_id)
    question = get_object_or_404(Question, id=question_id, section__version__survey=survey)
    form = QuestionEditorForm(request.POST, instance=question)
    if not form.is_valid():
        return JsonResponse({'errors': form.errors.get_json_data()}, status=422)
    try:
        _, revision = services.update_question(
            question.id,
            _revision(request),
            form.cleaned_data,
            form.question_config(),
            form.cleaned_data['choice_labels'],
            form.cleaned_data['row_labels'],
        )
    except (services.StaleVersionError, ValidationError) as error:
        return _mutation_error(request, survey, error)
    return JsonResponse({'revision': revision})


@require_POST
@login_required
def question_move(request, survey_id, question_id):
    survey = _owned_survey(request, survey_id)
    question = get_object_or_404(Question, id=question_id, section__version__survey=survey)
    direction = request.POST.get('direction')
    if direction not in {'up', 'down'}:
        return JsonResponse({'error': 'Invalid direction.'}, status=422)
    try:
        services.move_question(question.id, _revision(request), direction)
    except (services.StaleVersionError, ValidationError) as error:
        return _mutation_error(request, survey, error)
    return redirect(f"{reverse('survey_builder', args=[survey.id])}?question={question.id}")


@require_POST
@login_required
def question_delete(request, survey_id, question_id):
    survey = _owned_survey(request, survey_id)
    question = get_object_or_404(Question, id=question_id, section__version__survey=survey)
    try:
        services.delete_question(question.id, _revision(request))
    except (services.StaleVersionError, ValidationError) as error:
        return _mutation_error(request, survey, error)
    return redirect('survey_builder', survey_id=survey.id)
