from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from responses.models import Submission
from sharing.permissions import EDIT_ROLES, OWNER_ROLES, VIEW_ROLES, accessible_surveys, get_accessible_survey

from . import services
from .publication import PublicationError, branch_cycle_sections, publish_survey, readiness_errors
from .forms import (
    EligibilityCriteriaForm,
    QuestionBranchForm,
    QuestionEditorForm,
    ResponseLimitForm,
    SectionForm,
    SurveyMetadataForm,
)
from .models import BranchRule, Question, Section, Survey, SurveyVersion


@login_required
def survey_list(request):
    services.discard_empty_drafts(request.user)
    accessible = list(accessible_surveys(request.user, VIEW_ROLES).prefetch_related('topics'))

    # Completed-response counts for every accessible survey, in one query.
    response_counts = dict(
        Submission.objects.filter(
            survey__in=accessible,
            status=Submission.Status.COMPLETED,
        )
        .values_list('survey')
        .annotate(total=Count('id'))
    )
    for survey in accessible:
        survey.response_count = response_counts.get(survey.id, 0)

    owned_all = [s for s in accessible if s.owner_id == request.user.id]
    shared_surveys = [s for s in accessible if s.owner_id != request.user.id]

    status_counts = {
        'all': len(owned_all),
        'draft': sum(1 for s in owned_all if s.status == Survey.Status.DRAFT),
        'published': sum(1 for s in owned_all if s.status == Survey.Status.PUBLISHED),
        'closed': sum(1 for s in owned_all if s.status == Survey.Status.CLOSED),
    }

    status_filter = request.GET.get('status')
    if status_filter not in {'draft', 'published', 'closed'}:
        status_filter = 'all'
    owned_surveys = (
        owned_all if status_filter == 'all'
        else [s for s in owned_all if s.status == status_filter]
    )

    deleted_surveys = Survey.objects.filter(owner=request.user, deleted_at__isnull=False).order_by('-deleted_at')
    return render(
        request,
        'surveys/survey_list.html',
        {
            'owned_surveys': owned_surveys,
            'shared_surveys': shared_surveys,
            'status_counts': status_counts,
            'status_filter': status_filter,
            'has_owned': bool(owned_all),
            'deleted_surveys': deleted_surveys,
        },
    )


@require_POST
@login_required
def survey_create(request):
    survey = Survey.objects.create(owner=request.user, title=services.DEFAULT_SURVEY_TITLE, summary='')
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
    wants_json = (
        'application/json' in request.headers.get('Accept', '')
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.POST.get('autosave') == '1'
    )
    form = SurveyMetadataForm(instance=survey)
    response_limit_form = ResponseLimitForm(
        initial={
            'enabled': version.response_limit is not None if version else False,
            'response_limit': version.response_limit if version else None,
        }
    )
    criteria = getattr(version, 'eligibility_criteria', None) if version else None
    eligibility_form = EligibilityCriteriaForm(
        initial={
            'restrict_age': bool(criteria and (criteria.min_age is not None or criteria.max_age is not None)),
            'min_age': criteria.min_age if criteria else None,
            'max_age': criteria.max_age if criteria else None,
            'restrict_education': bool(criteria and criteria.education_levels),
            'education_levels': criteria.education_levels if criteria else [],
            'restrict_countries': bool(criteria and criteria.countries),
            'countries': criteria.countries if criteria else [],
            'restrict_regions': bool(criteria and criteria.regions),
            'regions': criteria.regions if criteria else [],
            'restrict_genders': bool(criteria and criteria.genders),
            'genders': criteria.genders if criteria else [],
            'restrict_employment': bool(criteria and criteria.employment_statuses),
            'employment_statuses': criteria.employment_statuses if criteria else [],
            'restrict_industries': bool(criteria and criteria.industries),
            'industries': criteria.industries if criteria else [],
            'restrict_income': bool(criteria and criteria.income_brackets),
            'income_brackets': criteria.income_brackets if criteria else [],
            'restrict_religions': bool(criteria and criteria.religions),
            'religions': criteria.religions if criteria else [],
            'restrict_ethnicities': bool(criteria and criteria.ethnicities),
            'ethnicities': criteria.ethnicities if criteria else [],
            'restrict_languages': bool(criteria and criteria.languages),
            'languages': criteria.languages if criteria else [],
        }
    )
    if request.method == 'POST':
        action = request.POST.get('action', 'metadata')
        try:
            if action == 'metadata':
                form = SurveyMetadataForm(request.POST, request.FILES, instance=survey)
                if form.is_valid():
                    form.save()
                    if wants_json:
                        return JsonResponse({'revision': version.revision if version else None})
                    messages.success(request, 'Survey settings saved.')
                    return redirect('survey_edit', survey_id=survey.id)
            elif action == 'update_response_limit' and version:
                response_limit_form = ResponseLimitForm(request.POST)
                if response_limit_form.is_valid():
                    revision = services.update_response_limit(
                        version.id,
                        _revision(request),
                        response_limit_form.cleaned_data['response_limit'],
                    )
                    if wants_json:
                        return JsonResponse({'revision': revision})
                    messages.success(request, 'Response limit updated.')
                    return redirect('survey_edit', survey_id=survey.id)
            elif action == 'update_eligibility' and version:
                eligibility_form = EligibilityCriteriaForm(request.POST)
                if eligibility_form.is_valid():
                    _, revision = services.update_eligibility(
                        version.id,
                        _revision(request),
                        eligibility_form.cleaned_data,
                    )
                    if wants_json:
                        return JsonResponse({'revision': revision})
                    messages.success(request, 'Eligibility criteria updated.')
                    return redirect('survey_edit', survey_id=survey.id)
        except (services.StaleVersionError, ValidationError) as error:
            if wants_json:
                message = (
                    'This survey changed in another tab. Reload before continuing.'
                    if isinstance(error, services.StaleVersionError)
                    else '; '.join(error.messages)
                )
                return JsonResponse({'error': message}, status=409 if isinstance(error, services.StaleVersionError) else 422)
            if isinstance(error, services.StaleVersionError):
                messages.error(request, 'This survey changed in another tab. Reload before continuing.')
            else:
                messages.error(request, '; '.join(error.messages))
            return redirect('survey_edit', survey_id=survey.id)

        if wants_json:
            action_forms = {
                'metadata': form,
                'update_eligibility': eligibility_form,
                'update_response_limit': response_limit_form,
            }
            invalid_form = action_forms.get(action)
            errors = invalid_form.errors.get_json_data() if invalid_form else {}
            return JsonResponse({'error': 'Check the highlighted settings.', 'errors': errors}, status=422)

    return render(
        request,
        'surveys/survey_form.html',
        {
            'form': form,
            'survey': survey,
            'version': version,
            'response_limit_form': response_limit_form,
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
def survey_response_collection(request, survey_id):
    survey = get_accessible_survey(request.user, survey_id, OWNER_ROLES)
    accepting = request.POST.get('accepting') == 'on'
    try:
        services.set_response_collection(survey.id, accepting)
    except ValidationError as error:
        messages.error(request, '; '.join(error.messages))
    else:
        state = 'accepting responses' if accepting else 'paused'
        messages.success(request, f'“{survey.title}” is now {state}.')
    return redirect('survey_edit', survey_id=survey.id)


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


def _annotate_branch_warnings(version, question, rules):
    """Attach a `.warnings` list to each rule so the builder can flag conditions
    that can never match or that trap respondents in a loop, inline where the
    creator is setting them up."""
    if not rules:
        return
    cycle_sections = branch_cycle_sections(version)
    allowed = set(BranchRule.allowed_operators(question.type))
    choice_labels = (
        set(question.choices.values_list('label', flat=True)) if question.accepts_choices else None
    )
    for rule in rules:
        warnings = []
        if rule.operator not in allowed:
            warnings.append(
                f'“{rule.get_operator_display()}” doesn’t apply to a {question.get_type_display()} '
                'question, so this rule can never match. Pick another condition.'
            )
        if (
            rule.action == BranchRule.Action.GO_TO_SECTION
            and question.section_id in cycle_sections
            and rule.target_section_id in cycle_sections
        ):
            warnings.append(
                'This jump loops back to a section that leads here again — respondents could '
                'never finish. Send them to a later section or “End survey”.'
            )
        if (
            choice_labels is not None
            and rule.operator != BranchRule.Operator.ANSWERED
            and rule.compare_value
            and rule.compare_value not in choice_labels
        ):
            warnings.append(
                f'“{rule.compare_value}” is no longer one of this question’s options, '
                'so this rule will never trigger.'
            )
        rule.warnings = warnings


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
        branch_rules = list(
            selected_question.branch_rules.select_related('target_section').order_by('order')
        )
        _annotate_branch_warnings(version, selected_question, branch_rules)
    sections, question_total = _annotate_questions(version)
    branched_ids = set(version.branch_rules.values_list('source_question_id', flat=True))
    for section in sections:
        for question in section.questions.all():
            question.has_branching = question.id in branched_ids
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
    after_order = None
    after_id = request.POST.get('after_question_id')
    if after_id:
        after = Question.objects.filter(id=after_id, section=section).values_list('order', flat=True).first()
        if after is not None:
            after_order = after
    try:
        question, _ = services.add_question(section.id, question_type, _revision(request), after_order)
    except (services.StaleVersionError, ValidationError) as error:
        return _mutation_error(request, survey, error)
    return redirect(f"{reverse('survey_builder', args=[survey.id])}?question={question.id}")


@require_POST
@login_required
def question_duplicate(request, survey_id, question_id):
    survey = _editable_survey(request, survey_id)
    question = get_object_or_404(Question, id=question_id, section__version__survey=survey)
    try:
        clone, _ = services.duplicate_question(question.id, _revision(request))
    except (services.StaleVersionError, ValidationError) as error:
        return _mutation_error(request, survey, error)
    return redirect(f"{reverse('survey_builder', args=[survey.id])}?question={clone.id}")


@require_POST
@login_required
def question_reorder(request, survey_id, question_id):
    survey = _editable_survey(request, survey_id)
    version = _draft_version(survey)
    question = get_object_or_404(Question, id=question_id, section__version=version)
    section = get_object_or_404(Section, id=request.POST.get('section_id'), version=version)
    try:
        position = int(request.POST.get('position', ''))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Invalid position.'}, status=422)
    try:
        services.reorder_question(question.id, _revision(request), section.id, position)
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
