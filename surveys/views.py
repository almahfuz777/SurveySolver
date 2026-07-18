from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from sharing.permissions import EDIT_ROLES, OWNER_ROLES, VIEW_ROLES, accessible_surveys, get_accessible_survey

from . import services
from .publication import PublicationError, publish_survey, readiness_errors
from .forms import (
    EligibilityCriteriaForm,
    QuestionBranchForm,
    QuestionEditorForm,
    QuotaForm,
    SectionForm,
    SurveyMetadataForm,
)
from .models import BranchRule, Question, Quota, Section, Survey, SurveyVersion


@login_required
def survey_list(request):
    surveys = accessible_surveys(request.user, VIEW_ROLES).prefetch_related('topics')
    deleted_surveys = Survey.objects.filter(owner=request.user, deleted_at__isnull=False).order_by('-deleted_at')
    return render(
        request,
        'surveys/survey_list.html',
        {'surveys': surveys, 'deleted_surveys': deleted_surveys},
    )


@require_POST
@login_required
def survey_create(request):
    survey = Survey.objects.create(owner=request.user, title='Untitled survey', summary='')
    return redirect('survey_builder', survey_id=survey.id)


@login_required
def survey_detail(request, survey_id):
    survey = get_accessible_survey(request.user, survey_id, VIEW_ROLES)
    if survey.access_role in EDIT_ROLES and survey.status != Survey.Status.ARCHIVED:
        return redirect('survey_builder', survey_id=survey.id)
    return redirect('survey_preview', survey_id=survey.id)


@login_required
def survey_edit(request, survey_id):
    survey = get_accessible_survey(request.user, survey_id, EDIT_ROLES)
    version = survey.draft_version
    form = SurveyMetadataForm(instance=survey)
    quota_form = QuotaForm()
    criteria = getattr(version, 'eligibility_criteria', None) if version else None
    eligibility_form = EligibilityCriteriaForm(
        initial={
            'min_age': criteria.min_age if criteria else None,
            'max_age': criteria.max_age if criteria else None,
            'education_levels': criteria.education_levels if criteria else [],
            'countries': criteria.countries if criteria else [],
            'genders': criteria.genders if criteria else [],
            'employment_statuses': criteria.employment_statuses if criteria else [],
        }
    )
    if request.method == 'POST':
        action = request.POST.get('action', 'metadata')
        try:
            if action == 'metadata':
                form = SurveyMetadataForm(request.POST, request.FILES, instance=survey)
                if form.is_valid():
                    form.save()
                    messages.success(request, 'Survey settings saved.')
                    return redirect('survey_edit', survey_id=survey.id)
            elif action == 'add_quota' and version:
                quota_form = QuotaForm(request.POST)
                if quota_form.is_valid():
                    services.add_quota(version.id, _revision(request), quota_form.cleaned_data)
                    messages.success(request, 'Quota added.')
                    return redirect('survey_edit', survey_id=survey.id)
            elif action == 'delete_quota' and version:
                quota = get_object_or_404(Quota, id=request.POST.get('quota_id'), version=version)
                services.delete_quota(quota.id, _revision(request))
                messages.success(request, 'Quota removed.')
                return redirect('survey_edit', survey_id=survey.id)
            elif action == 'update_eligibility' and version:
                eligibility_form = EligibilityCriteriaForm(request.POST)
                if eligibility_form.is_valid():
                    services.update_eligibility(version.id, _revision(request), eligibility_form.cleaned_data)
                    messages.success(request, 'Eligibility criteria updated.')
                    return redirect('survey_edit', survey_id=survey.id)
        except (services.StaleVersionError, ValidationError) as error:
            if isinstance(error, services.StaleVersionError):
                messages.error(request, 'This survey changed in another tab. Reload before continuing.')
            else:
                messages.error(request, '; '.join(error.messages))
            return redirect('survey_edit', survey_id=survey.id)

    return render(
        request,
        'surveys/survey_form.html',
        {
            'form': form,
            'survey': survey,
            'version': version,
            'quota_form': quota_form,
            'eligibility_form': eligibility_form,
            'readiness_errors': readiness_errors(version) if version else [],
            'page_title': 'Survey settings',
        },
    )


@require_POST
@login_required
def survey_archive(request, survey_id):
    survey = get_accessible_survey(request.user, survey_id, OWNER_ROLES)
    survey.archive()
    messages.success(request, 'Survey archived.')
    return redirect('survey_list')


@require_POST
@login_required
def survey_rename(request, survey_id):
    survey = get_accessible_survey(request.user, survey_id, EDIT_ROLES)
    title = request.POST.get('title', '').strip()
    if not title:
        return JsonResponse({'errors': {'title': [{'message': 'Enter a survey title.'}]}}, status=422)
    if len(title) > 160:
        return JsonResponse({'errors': {'title': [{'message': 'Keep the title under 160 characters.'}]}}, status=422)
    survey.title = title
    survey.save(update_fields=('title', 'updated_at'))
    return JsonResponse({'title': survey.title})


@require_POST
@login_required
def survey_delete(request, survey_id):
    survey = get_object_or_404(Survey.objects.active(), id=survey_id, owner=request.user)
    survey.soft_delete()
    messages.success(request, f'“{survey.title}” moved to recently deleted.')
    return redirect('survey_list')


@require_POST
@login_required
def survey_restore(request, survey_id):
    survey = get_object_or_404(Survey, id=survey_id, owner=request.user, deleted_at__isnull=False)
    survey.restore()
    messages.success(request, f'“{survey.title}” restored.')
    return redirect('survey_list')


@require_POST
@login_required
def survey_purge(request, survey_id):
    survey = get_object_or_404(Survey, id=survey_id, owner=request.user, deleted_at__isnull=False)
    if survey.has_response_history:
        messages.error(
            request,
            'This survey has collected responses, so it cannot be deleted forever. It stays in recently deleted.',
        )
        return redirect('survey_list')
    title = survey.title
    survey.versions.all().delete()
    survey.delete()
    messages.success(request, f'“{title}” deleted forever.')
    return redirect('survey_list')


@require_POST
@login_required
def survey_publish(request, survey_id):
    survey = _editable_survey(request, survey_id)
    try:
        published_version, _ = publish_survey(survey.id, request.user, _revision(request))
    except services.StaleVersionError:
        messages.error(request, 'This draft changed in another tab. Reload before publishing.')
    except PublicationError as error:
        for message in error.errors:
            messages.error(request, message)
    else:
        messages.success(request, 'Survey published. Respondents now see the latest questions.')
    return redirect('survey_builder', survey_id=survey.id)


def _editable_survey(request, survey_id):
    return get_accessible_survey(request.user, survey_id, EDIT_ROLES)


def _draft_version(survey):
    return get_object_or_404(
        SurveyVersion.objects.prefetch_related(
            'sections__questions__choices',
            'sections__questions__matrix_rows',
        ),
        survey=survey,
        status=SurveyVersion.Status.DRAFT,
    )


def _annotate_questions(version):
    """Attach presentation attributes (continuous number, scale points) to the
    prefetched question instances used by the responder-view templates."""
    sections = list(version.sections.all())
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
    survey = _editable_survey(request, survey_id)
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
    branch_form = None
    branch_rules = []
    if selected_question:
        branch_form = QuestionBranchForm(version=version, question=selected_question)
        branch_rules = selected_question.branch_rules.select_related('target_section').order_by('order')
    sections, question_total = _annotate_questions(version)
    if selected_question:
        toolbar_section_id = selected_question.section_id
        selected_question.number = next(
            (
                question.number
                for section in sections
                for question in section.questions.all()
                if question.id == selected_question.id
            ),
            question_total,
        )
    else:
        toolbar_section_id = sections[-1].id if sections else None
    return render(
        request,
        'surveys/builder.html',
        {
            'survey': survey,
            'version': version,
            'question_types': Question.Type.choices,
            'selected_question': selected_question,
            'editor_form': editor_form,
            'branch_form': branch_form,
            'branch_rules': branch_rules,
            'readiness_errors': readiness_errors(version),
            'sections': sections,
            'question_total': question_total,
            'toolbar_section_id': toolbar_section_id,
        },
    )


@login_required
def survey_preview(request, survey_id):
    survey = get_accessible_survey(request.user, survey_id, VIEW_ROLES)
    version = _draft_version(survey)
    sections, question_total = _annotate_questions(version)
    return render(
        request,
        'surveys/preview.html',
        {
            'survey': survey,
            'version': version,
            'sections': sections,
            'question_total': question_total,
        },
    )


@require_POST
@login_required
def question_branch_add(request, survey_id, question_id):
    survey = _editable_survey(request, survey_id)
    version = _draft_version(survey)
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
            _revision(request),
            {'source_question': question, **form.cleaned_data},
        )
    except (services.StaleVersionError, ValidationError) as error:
        return _mutation_error(request, survey, error)
    messages.success(request, 'Logic rule added.')
    return redirect(f"{reverse('survey_builder', args=[survey.id])}?question={question.id}")


@require_POST
@login_required
def question_branch_delete(request, survey_id, rule_id):
    survey = _editable_survey(request, survey_id)
    rule = get_object_or_404(BranchRule, id=rule_id, version__survey=survey)
    question_id = rule.source_question_id
    try:
        services.delete_branch_rule(rule.id, _revision(request))
    except (services.StaleVersionError, ValidationError) as error:
        return _mutation_error(request, survey, error)
    messages.success(request, 'Logic rule removed.')
    return redirect(f"{reverse('survey_builder', args=[survey.id])}?question={question_id}")


@require_POST
@login_required
def section_add(request, survey_id):
    survey = _editable_survey(request, survey_id)
    version = _draft_version(survey)
    try:
        services.add_section(version.id, _revision(request))
    except (services.StaleVersionError, ValidationError) as error:
        return _mutation_error(request, survey, error)
    return redirect('survey_builder', survey_id=survey.id)


@require_POST
@login_required
def section_update(request, survey_id, section_id):
    survey = _editable_survey(request, survey_id)
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
    survey = _editable_survey(request, survey_id)
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
    survey = _editable_survey(request, survey_id)
    section = get_object_or_404(Section, id=section_id, version__survey=survey)
    try:
        services.delete_section(section.id, _revision(request))
    except (services.StaleVersionError, ValidationError) as error:
        return _mutation_error(request, survey, error)
    return redirect('survey_builder', survey_id=survey.id)


@require_POST
@login_required
def question_add(request, survey_id):
    survey = _editable_survey(request, survey_id)
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
    survey = _editable_survey(request, survey_id)
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
    survey = _editable_survey(request, survey_id)
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
    survey = _editable_survey(request, survey_id)
    question = get_object_or_404(Question, id=question_id, section__version__survey=survey)
    try:
        services.delete_question(question.id, _revision(request))
    except (services.StaleVersionError, ValidationError) as error:
        return _mutation_error(request, survey, error)
    return redirect('survey_builder', survey_id=survey.id)
