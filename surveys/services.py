from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Exists, Max, OuterRef
from django.utils import timezone

from .models import BranchRule, EligibilityCriteria, MatrixRow, Question, QuestionChoice, Section, Survey, SurveyVersion

# Title stamped on a freshly created survey before the owner has edited anything.
DEFAULT_SURVEY_TITLE = 'Untitled survey'


class StaleVersionError(Exception):
    pass


def discard_empty_drafts(user):
    """Hard-delete the user's pristine, never-touched draft surveys.

    A survey is created the moment the owner clicks "Create survey", so an
    accidental click (or a builder opened and abandoned without adding a
    question) leaves an untouched draft behind. Sweep those away: still a
    DRAFT, default title, no summary/description, no questions, no responses.
    """
    has_questions = Question.objects.filter(section__version__survey=OuterRef('pk'))
    Survey.objects.filter(
        owner=user,
        deleted_at__isnull=True,
        status=Survey.Status.DRAFT,
        title=DEFAULT_SURVEY_TITLE,
        summary='',
        description='',
        banner='',
        thumbnail='',
        submissions__isnull=True,
    ).annotate(has_questions=Exists(has_questions)).filter(has_questions=False).delete()


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
def add_question(section_id, question_type, expected_revision, after_order=None):
    section = Section.objects.select_related('version').get(pk=section_id)
    version = _lock_version(section.version_id, expected_revision)
    if after_order is None:
        order = (section.questions.aggregate(max_order=Max('order'))['max_order'] or 0) + 1
    else:
        order = after_order + 1
        # Open a slot at `order` by shifting the tail down, highest first so the
        # per-(section, order) unique constraint never collides mid-shift.
        for existing in section.questions.filter(order__gte=order).order_by('-order'):
            Question.objects.filter(pk=existing.pk).update(order=existing.order + 1)
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
def duplicate_question(question_id, expected_revision):
    original = (
        Question.objects.select_related('section__version')
        .prefetch_related('choices', 'matrix_rows')
        .get(pk=question_id)
    )
    version = _lock_version(original.section.version_id, expected_revision)
    section = original.section
    order = original.order + 1
    for existing in section.questions.filter(order__gte=order).order_by('-order'):
        Question.objects.filter(pk=existing.pk).update(order=existing.order + 1)
    clone = Question.objects.create(
        section=section,
        type=original.type,
        prompt=original.prompt,
        help_text=original.help_text,
        required=original.required,
        randomize_choices=original.randomize_choices,
        order=order,
        config=original.config,
    )
    QuestionChoice.objects.bulk_create(
        [QuestionChoice(question=clone, label=choice.label, order=choice.order) for choice in original.choices.all()]
    )
    MatrixRow.objects.bulk_create(
        [MatrixRow(question=clone, label=row.label, order=row.order) for row in original.matrix_rows.all()]
    )
    return clone, _bump_revision(version)


@transaction.atomic
def reorder_question(question_id, expected_revision, target_section_id, position):
    """Move a question to `target_section_id` at 0-based `position`, supporting
    both within-section reordering and cross-section moves (drag and drop)."""
    question = Question.objects.select_related('section__version').get(pk=question_id)
    version = _lock_version(question.section.version_id, expected_revision)
    target_section = Section.objects.select_related('version').get(pk=target_section_id)
    if target_section.version_id != version.id:
        raise ValidationError('Target section must belong to this survey version.')

    source_section = question.section
    target_questions = list(
        Question.objects.filter(section=target_section).exclude(pk=question.pk).order_by('order')
    )
    position = max(0, min(int(position), len(target_questions)))
    target_questions.insert(position, question)

    # Two-phase renumber: park every touched row at a high, collision-free order
    # first, then assign the final 1..n. Keeps the (section, order) unique
    # constraint satisfied at every intermediate step.
    offset = 100000
    if source_section.id != target_section.id:
        source_questions = list(
            Question.objects.filter(section=source_section).exclude(pk=question.pk).order_by('order')
        )
        for index, item in enumerate(source_questions):
            Question.objects.filter(pk=item.pk).update(order=offset + index)
    for index, item in enumerate(target_questions):
        Question.objects.filter(pk=item.pk).update(section=target_section, order=offset + index)

    if source_section.id != target_section.id:
        for index, item in enumerate(source_questions, start=1):
            Question.objects.filter(pk=item.pk).update(order=index)
    for index, item in enumerate(target_questions, start=1):
        Question.objects.filter(pk=item.pk).update(order=index)

    return _bump_revision(version)


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
        'regions',
        'genders',
        'employment_statuses',
        'industries',
        'income_brackets',
        'religions',
        'ethnicities',
        'languages',
    )
    defaults = {}
    for field in criteria_fields:
        default = None if field in ('min_age', 'max_age') else []
        defaults[field] = cleaned_data.get(field, default)
    criteria, _ = EligibilityCriteria.objects.update_or_create(
        version=version,
        defaults=defaults,
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
