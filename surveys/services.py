from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Exists, Max, OuterRef
from django.utils import timezone

from .models import (
    ChoiceIdentity,
    MatrixRow,
    MatrixRowIdentity,
    Question,
    QuestionChoice,
    QuestionIdentity,
    Section,
    SectionIdentity,
    Survey,
    SurveyBranchRule,
    SurveyEligibilityCriteria,
    SurveyVersion,
)

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
    candidates = Survey.objects.filter(
        owner=user,
        deleted_at__isnull=True,
        status=Survey.Status.DRAFT,
        title=DEFAULT_SURVEY_TITLE,
        summary='',
        description='',
        banner='',
        thumbnail='',
        submissions__isnull=True,
    ).annotate(has_questions=Exists(has_questions)).filter(has_questions=False)
    # SurveyQuerySet.delete() routes each survey through Survey.delete(), so the
    # versions and identity hierarchy come down safely and atomically.
    candidates.delete()


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


def _version_section_identities(version):
    return SectionIdentity.objects.filter(
        snapshots__version=version,
    ).distinct()


def _version_question_identities(version, section_identity=None):
    queryset = QuestionIdentity.objects.filter(
        snapshots__section__version=version,
    ).distinct()
    if section_identity is not None:
        queryset = queryset.filter(section_identity=section_identity)
    return queryset


@transaction.atomic
def add_section(version_id, expected_revision):
    version = _lock_version(version_id, expected_revision)
    order = (
        _version_section_identities(version).aggregate(max_order=Max('order'))['max_order']
        or 0
    ) + 1
    identity = SectionIdentity.objects.create(survey=version.survey, order=order)
    legacy_order = (version.sections.aggregate(max_order=Max('order'))['max_order'] or 0) + 1
    section = Section.objects.create(
        version=version,
        identity=identity,
        title=f'Section {order}',
        order=legacy_order,
    )
    return section, _bump_revision(version)


@transaction.atomic
def update_section(section_id, expected_revision, cleaned_data):
    section = Section.objects.select_related('version').get(pk=section_id)
    version = _lock_version(section.version_id, expected_revision)
    section.title = cleaned_data['title']
    section.description = cleaned_data['description']
    section.save(update_fields=('title', 'description'))
    SectionIdentity.objects.filter(pk=section.identity_id).update(
        randomize_questions=cleaned_data['randomize_questions'],
    )
    section.randomize_questions = cleaned_data['randomize_questions']
    return section, _bump_revision(version)


@transaction.atomic
def move_section(section_id, expected_revision, direction):
    if direction not in {'up', 'down'}:
        raise ValidationError('Invalid move direction.')
    section = Section.objects.select_related('version').get(pk=section_id)
    version = _lock_version(section.version_id, expected_revision)
    identity = section.identity
    queryset = _version_section_identities(version)
    adjacent = queryset.filter(
        **({'order__lt': identity.order} if direction == 'up' else {'order__gt': identity.order})
    ).order_by('-order' if direction == 'up' else 'order').first()
    if adjacent:
        section_order, adjacent_order = identity.order, adjacent.order
        SectionIdentity.objects.filter(pk=identity.pk).update(order=adjacent_order)
        SectionIdentity.objects.filter(pk=adjacent.pk).update(order=section_order)
    return _bump_revision(version)


@transaction.atomic
def delete_section(section_id, expected_revision):
    section = Section.objects.select_related('version').get(pk=section_id)
    version = _lock_version(section.version_id, expected_revision)
    if version.sections.count() == 1:
        raise ValidationError('A survey must contain at least one section.')
    removed_order = section.identity.order
    fallback_section = version.sections.exclude(pk=section.pk).order_by('order').first()
    fallback_order = (
        fallback_section.questions.aggregate(max_order=Max('order'))['max_order'] or 0
    )
    for moved_question in section.questions.exclude(
        identity__section_identity_id=section.identity_id,
    ):
        fallback_order += 1
        Question.objects.filter(pk=moved_question.pk).update(
            section=fallback_section,
            order=fallback_order,
        )
    logical_questions = Question.objects.filter(
        section__version=version,
        identity__section_identity_id=section.identity_id,
    )
    logical_questions.delete()
    section.delete()
    _version_section_identities(version).filter(order__gt=removed_order).update(
        order=models.F('order') - 1,
    )
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
    section_identity = section.identity
    if after_order is None:
        order = (
            _version_question_identities(version, section_identity).aggregate(
                max_order=Max('order')
            )['max_order']
            or 0
        ) + 1
    else:
        order = after_order + 1
        _version_question_identities(version, section_identity).filter(
            order__gte=order,
        ).update(order=models.F('order') + 1)
    config, choices, rows = _default_question_values(question_type)
    identity = QuestionIdentity.objects.create(
        survey=version.survey,
        section_identity=section_identity,
        order=order,
    )
    legacy_order = (section.questions.aggregate(max_order=Max('order'))['max_order'] or 0) + 1
    question = Question.objects.create(
        section=section,
        identity=identity,
        type=question_type,
        prompt='Untitled question',
        order=legacy_order,
        config=config,
    )
    for index, label in enumerate(choices, 1):
        choice_identity = ChoiceIdentity.objects.create(
            survey=version.survey,
            question_identity=identity,
            order=index,
        )
        QuestionChoice.objects.create(
            question=question,
            identity=choice_identity,
            label=label,
            order=index,
        )
    for index, label in enumerate(rows, 1):
        row_identity = MatrixRowIdentity.objects.create(
            survey=version.survey,
            question_identity=identity,
            order=index,
        )
        MatrixRow.objects.create(
            question=question,
            identity=row_identity,
            label=label,
            order=index,
        )
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
    section_identity = original.identity.section_identity
    order = original.identity.order + 1
    _version_question_identities(version, section_identity).filter(
        order__gte=order,
    ).update(order=models.F('order') + 1)
    identity = QuestionIdentity.objects.create(
        survey=version.survey,
        section_identity=section_identity,
        order=order,
        required=original.identity.required,
        randomize_choices=original.identity.randomize_choices,
    )
    legacy_order = (section.questions.aggregate(max_order=Max('order'))['max_order'] or 0) + 1
    clone = Question.objects.create(
        section=section,
        identity=identity,
        type=original.type,
        prompt=original.prompt,
        help_text=original.help_text,
        required=False,
        randomize_choices=False,
        order=legacy_order,
        config=original.config,
    )
    for choice in original.choices.select_related('identity').all():
        choice_identity = ChoiceIdentity.objects.create(
            survey=version.survey,
            question_identity=identity,
            order=choice.identity.order,
        )
        QuestionChoice.objects.create(
            question=clone,
            identity=choice_identity,
            label=choice.label,
            order=choice.order,
        )
    for row in original.matrix_rows.select_related('identity').all():
        row_identity = MatrixRowIdentity.objects.create(
            survey=version.survey,
            question_identity=identity,
            order=row.identity.order,
        )
        MatrixRow.objects.create(
            question=clone,
            identity=row_identity,
            label=row.label,
            order=row.order,
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

    source_section_identity = question.identity.section_identity
    target_section_identity = target_section.identity

    # Placement applies live to the active version. A section added since the
    # last publish has no snapshot there, so moving a live question into it
    # would silently drop that question from the published survey — for any
    # active version, whether or not it has collected responses yet. Block the
    # move until the new section is itself published.
    if source_section_identity.id != target_section_identity.id:
        active = version.survey.versions.filter(
            status=SurveyVersion.Status.PUBLISHED,
        ).first()
        if active is not None:
            question_is_live = Section.objects.filter(
                version=active,
                questions__identity=question.identity,
            ).exists()
            target_is_live = Section.objects.filter(
                version=active,
                identity=target_section_identity,
            ).exists()
            if question_is_live and not target_is_live:
                raise ValidationError(
                    'Publish your new section before moving live questions into it.'
                )

    target_questions = list(
        _version_question_identities(version, target_section_identity)
        .exclude(pk=question.identity_id)
        .order_by('order', 'id')
    )
    position = max(0, min(int(position), len(target_questions)))
    target_questions.insert(position, question.identity)

    if source_section_identity.id != target_section_identity.id:
        source_questions = list(
            _version_question_identities(version, source_section_identity)
            .exclude(pk=question.identity_id)
            .order_by('order', 'id')
        )
    for index, item in enumerate(target_questions):
        QuestionIdentity.objects.filter(pk=item.pk).update(
            section_identity=target_section_identity,
            order=index + 1,
        )
    if source_section_identity.id != target_section_identity.id:
        for index, item in enumerate(source_questions, start=1):
            QuestionIdentity.objects.filter(pk=item.pk).update(order=index)

    return _bump_revision(version)


@transaction.atomic
def update_question(
    question_id,
    expected_revision,
    cleaned_data,
    config,
    choice_labels,
    row_labels=None,
    choice_identity_ids=None,
    row_identity_ids=None,
):
    question = Question.objects.select_related('section__version').get(pk=question_id)
    version = _lock_version(question.section.version_id, expected_revision)
    question.type = cleaned_data['type']
    question.prompt = cleaned_data['prompt']
    question.help_text = cleaned_data['help_text']
    question.config = config
    question.save(update_fields=('type', 'prompt', 'help_text', 'config'))
    QuestionIdentity.objects.filter(pk=question.identity_id).update(
        required=cleaned_data['required'],
        randomize_choices=cleaned_data['randomize_choices'],
    )
    _sync_choice_content(question, choice_labels, choice_identity_ids or [])
    _sync_matrix_row_content(question, row_labels or [], row_identity_ids or [])
    return question, _bump_revision(version)


def _plan_label_sync(existing, labels, identity_ids):
    """Pair each submitted label with the existing row it continues, if any."""
    planned = []
    claimed = set()
    for index, label in enumerate(labels, 1):
        identity_id = identity_ids[index - 1] if index <= len(identity_ids) else ''
        if identity_id and identity_id in existing and identity_id not in claimed:
            claimed.add(identity_id)
            planned.append((identity_id, label))
        else:
            planned.append((None, label))
    return planned, claimed


def _sync_label_rows(question, labels, identity_ids, *, manager, identity_model, snapshot_model):
    """Reconcile a question's choices or matrix statements against submitted labels.

    Rows carry both a legacy snapshot `order` (unique per question) and a live
    order on their identity. Dropped rows are deleted first and the survivors are
    parked at a collision-free offset before their final positions are written,
    so swapping one option for another can't trip the unique constraint
    mid-update.
    """
    existing = {
        str(row.identity_id): row
        for row in manager.select_related('identity')
    }
    planned, claimed = _plan_label_sync(existing, labels, identity_ids)

    for identity_id, row in existing.items():
        if identity_id not in claimed:
            row.delete()

    offset = 100000
    for position, (identity_id, _) in enumerate(planned):
        if identity_id:
            row = existing[identity_id]
            row.order = offset + position
            row.save(update_fields=('order',))

    survey = question.section.version.survey
    for index, (identity_id, label) in enumerate(planned, 1):
        if identity_id:
            row = existing[identity_id]
            row.label = label
            row.order = index
            row.save(update_fields=('label', 'order'))
            identity_model.objects.filter(pk=row.identity_id).update(order=index)
            continue
        identity = identity_model.objects.create(
            survey=survey,
            question_identity=question.identity,
            order=index,
        )
        snapshot_model.objects.create(
            question=question,
            identity=identity,
            label=label,
            order=index,
        )


def _sync_choice_content(question, labels, identity_ids):
    _sync_label_rows(
        question,
        labels,
        identity_ids,
        manager=question.choices,
        identity_model=ChoiceIdentity,
        snapshot_model=QuestionChoice,
    )


def _sync_matrix_row_content(question, labels, identity_ids):
    _sync_label_rows(
        question,
        labels,
        identity_ids,
        manager=question.matrix_rows,
        identity_model=MatrixRowIdentity,
        snapshot_model=MatrixRow,
    )


@transaction.atomic
def add_branch_rule(version_id, expected_revision, cleaned_data):
    version = _lock_version(version_id, expected_revision)
    source_question = cleaned_data.pop('source_question')
    target_section = cleaned_data.pop('target_section', None)
    compare_value = cleaned_data.get('compare_value', '')
    compare_choice = next(
        (
            choice
            for choice in source_question.choices.all()
            if choice.label == compare_value
        ),
        None,
    )
    order = (
        version.survey.presentation_branch_rules.aggregate(max_order=Max('order'))[
            'max_order'
        ]
        or 0
    ) + 1
    rule = SurveyBranchRule(
        survey=version.survey,
        source_question_identity=source_question.identity,
        target_section_identity=target_section.identity if target_section else None,
        compare_choice_identity=compare_choice.identity if compare_choice else None,
        order=order,
        **cleaned_data,
    )
    rule.full_clean()
    rule.save()
    return rule, _bump_revision(version)


@transaction.atomic
def delete_branch_rule(rule_id, expected_revision):
    rule = SurveyBranchRule.objects.select_related('survey').get(pk=rule_id)
    version = _lock_version(rule.survey.draft_version.id, expected_revision)
    rule.delete()
    return _bump_revision(version)


@transaction.atomic
def update_response_limit(version_id, expected_revision, response_limit):
    version = _lock_version(version_id, expected_revision)
    Survey.objects.filter(pk=version.survey_id).update(response_limit=response_limit)
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
    criteria, _ = SurveyEligibilityCriteria.objects.update_or_create(
        survey=version.survey,
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
    identity = question.identity
    queryset = _version_question_identities(version, identity.section_identity)
    adjacent = queryset.filter(
        **({'order__lt': identity.order} if direction == 'up' else {'order__gt': identity.order})
    ).order_by('-order' if direction == 'up' else 'order').first()
    if adjacent:
        question_order, adjacent_order = identity.order, adjacent.order
        QuestionIdentity.objects.filter(pk=identity.pk).update(order=adjacent_order)
        QuestionIdentity.objects.filter(pk=adjacent.pk).update(order=question_order)
    return _bump_revision(version)


@transaction.atomic
def delete_question(question_id, expected_revision):
    question = Question.objects.select_related('section__version').get(pk=question_id)
    version = _lock_version(question.section.version_id, expected_revision)
    identity = question.identity
    removed_order = identity.order
    question.delete()
    _version_question_identities(version, identity.section_identity).filter(
        order__gt=removed_order,
    ).update(order=models.F('order') - 1)
    return _bump_revision(version)
