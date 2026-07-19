from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .models import BranchRule, EligibilityCriteria, MatrixRow, Question, QuestionChoice, Section, Survey, SurveyVersion


class StaleVersionError(Exception):
    pass


def _lock_version(version_id, expected_revision):
    version = SurveyVersion.objects.select_for_update().get(pk=version_id)
    if version.status != SurveyVersion.Status.DRAFT:
        raise ValidationError('Published survey versions are immutable.')
    if version.revision != expected_revision:
        raise StaleVersionError
    return version


def _bump_revision(version):
    version.revision += 1
    version.save(update_fields=('revision', 'updated_at'))
    return version.revision


@transaction.atomic
def add_section(version_id, expected_revision):
    version = _lock_version(version_id, expected_revision)
    order = (version.sections.aggregate(max_order=Max('order'))['max_order'] or 0) + 1
    section = Section.objects.create(version=version, title=f'Section {order}', order=order)
    return section, _bump_revision(version)


@transaction.atomic
def update_section(section_id, expected_revision, cleaned_data):
    section = Section.objects.select_related('version').get(pk=section_id)
    version = _lock_version(section.version_id, expected_revision)
    section.title = cleaned_data['title']
    section.description = cleaned_data['description']
    section.randomize_questions = cleaned_data['randomize_questions']
    section.save(update_fields=('title', 'description', 'randomize_questions'))
    return section, _bump_revision(version)


@transaction.atomic
def move_section(section_id, expected_revision, direction):
    if direction not in {'up', 'down'}:
        raise ValidationError('Invalid move direction.')
    section = Section.objects.select_related('version').get(pk=section_id)
    version = _lock_version(section.version_id, expected_revision)
    queryset = Section.objects.filter(version=version)
    adjacent = queryset.filter(
        **({'order__lt': section.order} if direction == 'up' else {'order__gt': section.order})
    ).order_by('-order' if direction == 'up' else 'order').first()
    if adjacent:
        temporary_order = (queryset.aggregate(max_order=Max('order'))['max_order'] or 0) + 1
        section_order, adjacent_order = section.order, adjacent.order
        section.order = temporary_order
        section.save(update_fields=('order',))
        adjacent.order = section_order
        adjacent.save(update_fields=('order',))
        section.order = adjacent_order
        section.save(update_fields=('order',))
    return _bump_revision(version)


@transaction.atomic
def delete_section(section_id, expected_revision):
    section = Section.objects.select_related('version').get(pk=section_id)
    version = _lock_version(section.version_id, expected_revision)
    if version.sections.count() == 1:
        raise ValidationError('A survey must contain at least one section.')
    removed_order = section.order
    section.delete()
    for remaining in version.sections.filter(order__gt=removed_order).order_by('order'):
        remaining.order -= 1
        remaining.save(update_fields=('order',))
    return _bump_revision(version)


def _default_question_values(question_type):
    config = {'scale_min': 1, 'scale_max': 5} if question_type == Question.Type.SCALE else {}
    choices = ['Option 1', 'Option 2'] if question_type in {
        Question.Type.SINGLE_CHOICE,
        Question.Type.MULTIPLE_CHOICE,
        Question.Type.DROPDOWN,
        Question.Type.RANKING,
    } else []
    rows = []
    if question_type == Question.Type.LIKERT_MATRIX:
        choices = ['Strongly disagree', 'Disagree', 'Neutral', 'Agree', 'Strongly agree']
        rows = ['Statement 1', 'Statement 2']
    return config, choices, rows


@transaction.atomic
def add_question(section_id, question_type, expected_revision):
    section = Section.objects.select_related('version').get(pk=section_id)
    version = _lock_version(section.version_id, expected_revision)
    order = (section.questions.aggregate(max_order=Max('order'))['max_order'] or 0) + 1
    config, choices, rows = _default_question_values(question_type)
    question = Question.objects.create(
        section=section,
        type=question_type,
        prompt='Untitled question',
        order=order,
        config=config,
    )
    QuestionChoice.objects.bulk_create(
        [QuestionChoice(question=question, label=label, order=index) for index, label in enumerate(choices, 1)]
    )
    MatrixRow.objects.bulk_create([MatrixRow(question=question, label=label, order=index) for index, label in enumerate(rows, 1)])
    return question, _bump_revision(version)


@transaction.atomic
def update_question(question_id, expected_revision, cleaned_data, config, choice_labels, row_labels=None):
    question = Question.objects.select_related('section__version').get(pk=question_id)
    version = _lock_version(question.section.version_id, expected_revision)
    question.type = cleaned_data['type']
    question.prompt = cleaned_data['prompt']
    question.help_text = cleaned_data['help_text']
    question.required = cleaned_data['required']
    question.randomize_choices = cleaned_data['randomize_choices']
    question.config = config
    question.save(update_fields=('type', 'prompt', 'help_text', 'required', 'randomize_choices', 'config'))
    question.choices.all().delete()
    QuestionChoice.objects.bulk_create(
        [QuestionChoice(question=question, label=label, order=index) for index, label in enumerate(choice_labels, 1)]
    )
    question.matrix_rows.all().delete()
    MatrixRow.objects.bulk_create([MatrixRow(question=question, label=label, order=index) for index, label in enumerate(row_labels or [], 1)])
    return question, _bump_revision(version)


@transaction.atomic
def add_branch_rule(version_id, expected_revision, cleaned_data):
    version = _lock_version(version_id, expected_revision)
    order = (version.branch_rules.aggregate(max_order=Max('order'))['max_order'] or 0) + 1
    rule = BranchRule(version=version, order=order, **cleaned_data)
    rule.full_clean()
    rule.save()
    return rule, _bump_revision(version)


@transaction.atomic
def delete_branch_rule(rule_id, expected_revision):
    rule = BranchRule.objects.select_related('version').get(pk=rule_id)
    version = _lock_version(rule.version_id, expected_revision)
    rule.delete()
    return _bump_revision(version)


@transaction.atomic
def update_response_limit(version_id, expected_revision, response_limit):
    version = _lock_version(version_id, expected_revision)
    version.response_limit = response_limit
    version.save(update_fields=('response_limit',))
    return _bump_revision(version)


@transaction.atomic
def update_eligibility(version_id, expected_revision, cleaned_data):
    version = _lock_version(version_id, expected_revision)
    criteria_fields = (
        'min_age',
        'max_age',
        'education_levels',
        'countries',
        'genders',
        'employment_statuses',
    )
    criteria, _ = EligibilityCriteria.objects.update_or_create(
        version=version,
        defaults={field: cleaned_data[field] for field in criteria_fields},
    )
    return criteria, _bump_revision(version)


@transaction.atomic
def set_response_collection(survey_id, accepting):
    survey = Survey.objects.select_for_update().get(pk=survey_id)
    if survey.status not in {Survey.Status.PUBLISHED, Survey.Status.CLOSED}:
        raise ValidationError('Only published surveys can accept or pause responses.')
    if accepting and not survey.versions.filter(status=SurveyVersion.Status.PUBLISHED).exists():
        raise ValidationError('Publish a survey version before accepting responses.')

    target_status = Survey.Status.PUBLISHED if accepting else Survey.Status.CLOSED
    if survey.status == target_status:
        return survey

    survey.status = target_status
    survey.closed_at = None if accepting else timezone.now()
    survey.save(update_fields=('status', 'closed_at', 'updated_at'))
    return survey


@transaction.atomic
def move_question(question_id, expected_revision, direction):
    if direction not in {'up', 'down'}:
        raise ValidationError('Invalid move direction.')
    question = Question.objects.select_related('section__version').get(pk=question_id)
    version = _lock_version(question.section.version_id, expected_revision)
    queryset = Question.objects.filter(section=question.section)
    adjacent = queryset.filter(
        **({'order__lt': question.order} if direction == 'up' else {'order__gt': question.order})
    ).order_by('-order' if direction == 'up' else 'order').first()
    if adjacent:
        temporary_order = (queryset.aggregate(max_order=Max('order'))['max_order'] or 0) + 1
        question_order, adjacent_order = question.order, adjacent.order
        question.order = temporary_order
        question.save(update_fields=('order',))
        adjacent.order = question_order
        adjacent.save(update_fields=('order',))
        question.order = adjacent_order
        question.save(update_fields=('order',))
    return _bump_revision(version)


@transaction.atomic
def delete_question(question_id, expected_revision):
    question = Question.objects.select_related('section__version').get(pk=question_id)
    version = _lock_version(question.section.version_id, expected_revision)
    section = question.section
    removed_order = question.order
    question.delete()
    for remaining in section.questions.filter(order__gt=removed_order).order_by('order'):
        remaining.order -= 1
        remaining.save(update_fields=('order',))
    return _bump_revision(version)
