"""Editing a survey's draft: sections, questions and branching logic."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from sharing.permissions import VIEW_ROLES, get_accessible_survey

from . import branching, services
from .diff import question_change_map
from .presentation import resolved_version
from .publication import (
    branch_cycle_sections,
    publication_intent,
    readiness_errors,
)
from .forms import (
    QuestionBranchForm,
    QuestionEditorForm,
    SectionForm,
)
from .models import (
    Question,
    Section,
    SurveyBranchRule,
    SurveyVersion,
)
from .view_helpers import draft_version, editable_survey, posted_revision


# Sentinel for `?question=` meaning "the creator deliberately selected nothing".
NO_SELECTION = 'none'


def _annotate_questions(version):
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
    question_section_id = str(
        next(
            section.id
            for section in resolved_version(version)
            if section.identity_id == question.identity.section_identity_id
        )
    )
    allowed = set(branching.allowed_operators(question.type))
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
            rule.action == branching.Action.GO_TO_SECTION
            and question_section_id in cycle_sections
            and rule.target_section is not None
            and str(rule.target_section.id) in cycle_sections
        ):
            warnings.append(
                'This jump loops back to a section that leads here again — respondents could '
                'never finish. Send them to a later section or “End survey”.'
            )
        if (
            rule.action == branching.Action.GO_TO_SECTION
            and rule.target_section is None
        ):
            warnings.append(
                'The target section is not part of this draft, so this rule is inactive.'
            )
        if (
            choice_labels is not None
            and rule.operator != branching.Operator.ANSWERED
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
    survey = editable_survey(request, survey_id)
    version = draft_version(survey)
    selected_question = None
    selected_id = request.GET.get('question')
    # `?question=none` is an explicit "nothing selected" state (clicking empty
    # canvas space). Without the parameter at all we still default to the first
    # question, so opening the builder lands somewhere useful.
    deselected = selected_id == NO_SELECTION
    if selected_id and not deselected:
        selected_question = get_object_or_404(
            Question.objects.prefetch_related('choices'),
            id=selected_id,
            section__version=version,
        )
    sections, question_total = _annotate_questions(version)
    if selected_question:
        effective = next(
            (
                candidate
                for section in sections
                for candidate in section.questions.all()
                if candidate.id == selected_question.id
            ),
            None,
        )
        if effective is not None:
            selected_question = effective
    elif sections and not deselected:
        selected_question = next(
            (
                question
                for section in sections
                for question in section.questions.all()
            ),
            None,
        )
    editor_form = QuestionEditorForm(instance=selected_question) if selected_question else None
    branch_form = None
    branch_rules = []
    if selected_question:
        branch_form = QuestionBranchForm(version=version, question=selected_question)
        section_by_identity = {section.identity_id: section for section in sections}
        branch_rules = list(
            survey.presentation_branch_rules.filter(
                source_question_identity=selected_question.identity,
            )
            .select_related('target_section_identity', 'compare_choice_identity')
            .order_by('order')
        )
        for rule in branch_rules:
            rule._target_section_snapshot = section_by_identity.get(
                rule.target_section_identity_id
            )
            rule.target_section_id = (
                rule.target_section.id if rule.target_section is not None else None
            )
            if rule.compare_choice_identity_id:
                choice = next(
                    (
                        candidate
                        for candidate in selected_question.choices.all()
                        if candidate.identity_id == rule.compare_choice_identity_id
                    ),
                    None,
                )
                if choice:
                    rule.compare_value = choice.label
        _annotate_branch_warnings(version, selected_question, branch_rules)
    branched_ids = set(
        survey.presentation_branch_rules.values_list(
            'source_question_identity_id',
            flat=True,
        )
    )
    # Gutter markers: which questions differ from the live version, so the
    # creator can see unpublished edits in place without opening the review.
    change_map = question_change_map(
        version,
        survey.versions.filter(status=SurveyVersion.Status.PUBLISHED).first(),
    )
    for section in sections:
        for question in section.questions.all():
            question.has_branching = question.identity_id in branched_ids
            question.change_status = change_map.get(str(question.identity_id), '')
    if selected_question:
        toolbar_position, toolbar_section = next(
            (
                (position, section)
                for position, section in enumerate(sections, 1)
                if section.identity_id == selected_question.identity.section_identity_id
            ),
            (0, None),
        )
        toolbar_section_id = toolbar_section.id if toolbar_section else sections[0].id
        # "Section 2 · Screening" — the number always shows, the title only when
        # it adds something beyond the default "Section N" name.
        section_label = f'Section {toolbar_position}' if toolbar_position else 'Section'
        if toolbar_section and toolbar_section.title and toolbar_section.title != section_label:
            section_label = f'{section_label} · {toolbar_section.title}'
        selected_question.section_label = section_label
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
            'publication_intent': publication_intent(survey, version),
        },
    )


@login_required
def survey_preview(request, survey_id):
    survey = get_accessible_survey(request.user, survey_id, VIEW_ROLES)
    version = draft_version(survey)
    sections, question_total = _annotate_questions(version)
    return render(
        request,
        'surveys/preview.html',
        {
            'survey': survey,
            'version': version,
            'sections': sections,
            'question_total': question_total,
            'publication_intent': publication_intent(survey, version),
        },
    )


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
        return _mutation_error(request, survey, error)
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
        return _mutation_error(request, survey, error)
    messages.success(request, 'Logic rule removed.')
    return redirect(f"{reverse('survey_builder', args=[survey.id])}?question={question_id}")


@require_POST
@login_required
def section_add(request, survey_id):
    survey = editable_survey(request, survey_id)
    version = draft_version(survey)
    try:
        services.add_section(version.id, posted_revision(request))
    except (services.StaleVersionError, ValidationError) as error:
        return _mutation_error(request, survey, error)
    return redirect('survey_builder', survey_id=survey.id)


@require_POST
@login_required
def section_update(request, survey_id, section_id):
    survey = editable_survey(request, survey_id)
    section = get_object_or_404(Section, id=section_id, version__survey=survey)
    form = SectionForm(request.POST, instance=section)
    if not form.is_valid():
        return JsonResponse({'errors': form.errors.get_json_data()}, status=422)
    try:
        _, revision = services.update_section(section.id, posted_revision(request), form.cleaned_data)
    except (services.StaleVersionError, ValidationError) as error:
        return _mutation_error(request, survey, error)
    return JsonResponse({'revision': revision})


@require_POST
@login_required
def section_move(request, survey_id, section_id):
    survey = editable_survey(request, survey_id)
    section = get_object_or_404(Section, id=section_id, version__survey=survey)
    direction = request.POST.get('direction')
    if direction not in {'up', 'down'}:
        return JsonResponse({'error': 'Invalid direction.'}, status=422)
    try:
        services.move_section(section.id, posted_revision(request), direction)
    except (services.StaleVersionError, ValidationError) as error:
        return _mutation_error(request, survey, error)
    return redirect('survey_builder', survey_id=survey.id)


@require_POST
@login_required
def section_delete(request, survey_id, section_id):
    survey = editable_survey(request, survey_id)
    section = get_object_or_404(Section, id=section_id, version__survey=survey)
    try:
        services.delete_section(section.id, posted_revision(request))
    except (services.StaleVersionError, ValidationError) as error:
        return _mutation_error(request, survey, error)
    return redirect('survey_builder', survey_id=survey.id)


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
        return _mutation_error(request, survey, error)
    return redirect(f"{reverse('survey_builder', args=[survey.id])}?question={question.id}")


@require_POST
@login_required
def question_duplicate(request, survey_id, question_id):
    survey = editable_survey(request, survey_id)
    question = get_object_or_404(Question, id=question_id, section__version__survey=survey)
    try:
        clone, _ = services.duplicate_question(question.id, posted_revision(request))
    except (services.StaleVersionError, ValidationError) as error:
        return _mutation_error(request, survey, error)
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
        return _mutation_error(request, survey, error)
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
        return _mutation_error(request, survey, error)
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
        return _mutation_error(request, survey, error)
    return redirect(f"{reverse('survey_builder', args=[survey.id])}?question={question.id}")


@require_POST
@login_required
def question_delete(request, survey_id, question_id):
    survey = editable_survey(request, survey_id)
    question = get_object_or_404(Question, id=question_id, section__version__survey=survey)
    try:
        services.delete_question(question.id, posted_revision(request))
    except (services.StaleVersionError, ValidationError) as error:
        return _mutation_error(request, survey, error)
    return redirect('survey_builder', survey_id=survey.id)
