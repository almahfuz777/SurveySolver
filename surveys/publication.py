from copy import deepcopy

from django.db import transaction
from django.utils import timezone

from sharing.permissions import EDIT_ROLES, accessible_surveys

from .models import BranchRule, EligibilityCriteria, MatrixRow, Question, QuestionChoice, Quota, Section, Survey, SurveyVersion


class PublicationError(Exception):
    def __init__(self, errors):
        self.errors = errors
        super().__init__('Survey is not ready to publish.')


def readiness_errors(version):
    errors = []
    questions = list(
        Question.objects.filter(section__version=version)
        .prefetch_related('choices', 'matrix_rows')
        .select_related('section')
    )
    if not questions:
        errors.append('Add at least one question.')
    for question in questions:
        if question.accepts_choices and question.choices.count() < 2:
            errors.append(f'“{question.prompt}” needs at least two choices.')
        if question.uses_matrix_rows and question.matrix_rows.count() < 2:
            errors.append(f'“{question.prompt}” needs at least two matrix statements.')

    cycle_sections = branch_cycle_sections(version)
    if cycle_sections:
        titles = list(
            Section.objects.filter(id__in=cycle_sections).order_by('order').values_list('title', flat=True)
        )
        errors.append(
            'Branch rules loop between sections (' + ' ↔ '.join(titles) + '), '
            'so respondents can never reach the end. Point one of these rules at a '
            'later section or “End survey”.'
        )
    return errors


def branch_cycle_sections(version):
    """Return the set of section ids that take part in a go-to-section loop."""
    edges = {}
    for rule in version.branch_rules.filter(action=BranchRule.Action.GO_TO_SECTION).select_related('source_question'):
        if rule.target_section_id:
            edges.setdefault(rule.source_question.section_id, set()).add(rule.target_section_id)

    color = {}
    stack = []
    cycle = set()

    def visit(node):
        color[node] = 'grey'
        stack.append(node)
        for target in edges.get(node, ()):
            state = color.get(target)
            if state == 'grey' and target in stack:
                cycle.update(stack[stack.index(target):])
            elif state is None:
                visit(target)
        stack.pop()
        color[node] = 'black'

    for node in list(edges):
        if node not in color:
            visit(node)
    return cycle


def _clone_version(source, created_by):
    clone = SurveyVersion.objects.create(
        survey=source.survey,
        number=source.number + 1,
        created_by=created_by,
        response_limit=source.response_limit,
    )
    section_map = {}
    question_map = {}
    for section in source.sections.order_by('order'):
        cloned_section = Section.objects.create(
            version=clone,
            title=section.title,
            description=section.description,
            order=section.order,
            randomize_questions=section.randomize_questions,
        )
        section_map[section.id] = cloned_section
        for question in section.questions.order_by('order'):
            cloned_question = Question.objects.create(
                section=cloned_section,
                type=question.type,
                prompt=question.prompt,
                help_text=question.help_text,
                required=question.required,
                randomize_choices=question.randomize_choices,
                order=question.order,
                config=deepcopy(question.config),
            )
            question_map[question.id] = cloned_question
            QuestionChoice.objects.bulk_create(
                [QuestionChoice(question=cloned_question, label=choice.label, order=choice.order) for choice in question.choices.all()]
            )
            MatrixRow.objects.bulk_create(
                [MatrixRow(question=cloned_question, label=row.label, order=row.order) for row in question.matrix_rows.all()]
            )

    for rule in source.branch_rules.order_by('order'):
        BranchRule.objects.create(
            version=clone,
            source_question=question_map[rule.source_question_id],
            operator=rule.operator,
            compare_value=rule.compare_value,
            action=rule.action,
            target_section=section_map.get(rule.target_section_id),
            order=rule.order,
        )
    for quota in source.quotas.all():
        Quota.objects.create(
            version=clone,
            name=quota.name,
            limit=quota.limit,
            criteria=deepcopy(quota.criteria),
            is_active=quota.is_active,
        )
    if hasattr(source, 'eligibility_criteria'):
        criteria = source.eligibility_criteria
        EligibilityCriteria.objects.create(
            version=clone,
            min_age=criteria.min_age,
            max_age=criteria.max_age,
            education_levels=deepcopy(criteria.education_levels),
            countries=deepcopy(criteria.countries),
            genders=deepcopy(criteria.genders),
            employment_statuses=deepcopy(criteria.employment_statuses),
        )
    return clone


@transaction.atomic
def publish_survey(survey_id, user, expected_revision):
    survey = accessible_surveys(user, EDIT_ROLES).select_for_update().get(id=survey_id)
    if survey.status == Survey.Status.ARCHIVED:
        raise PublicationError(['Archived surveys cannot be published.'])
    version = SurveyVersion.objects.select_for_update().get(
        survey=survey,
        status=SurveyVersion.Status.DRAFT,
    )
    if version.revision != expected_revision:
        from .services import StaleVersionError
        raise StaleVersionError
    errors = readiness_errors(version)
    if errors:
        raise PublicationError(errors)

    SurveyVersion.objects.filter(
        survey=survey,
        status=SurveyVersion.Status.PUBLISHED,
    ).update(status=SurveyVersion.Status.RETIRED)
    now = timezone.now()
    version.status = SurveyVersion.Status.PUBLISHED
    version.published_at = now
    version.save(update_fields=('status', 'published_at', 'updated_at'))
    survey.status = Survey.Status.PUBLISHED
    survey.published_at = now
    survey.closed_at = None
    survey.save(update_fields=('status', 'published_at', 'closed_at', 'updated_at'))
    next_draft = _clone_version(version, user)
    return version, next_draft
