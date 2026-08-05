"""The Questions and Preview tabs of the authoring workspace."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from sharing.permissions import VIEW_ROLES, get_accessible_survey

from ...diff import question_change_map
from ...models import Question, SurveyVersion
from ...publication import publication_intent, readiness_errors
from ...view_helpers import draft_version, editable_survey
from ..context import NO_SELECTION, annotate_branch_warnings, annotate_questions
from ..forms import QuestionBranchForm, QuestionEditorForm


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
    sections, question_total = annotate_questions(version)
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
        annotate_branch_warnings(version, selected_question, branch_rules)
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
        'surveys/builder/builder.html',
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
    sections, question_total = annotate_questions(version)
    return render(
        request,
        'surveys/builder/preview.html',
        {
            'survey': survey,
            'version': version,
            'sections': sections,
            'question_total': question_total,
            'publication_intent': publication_intent(survey, version),
        },
    )
