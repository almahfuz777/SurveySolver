"""Adding, editing, reordering and removing a draft's questions."""
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Max

from ..models import (
    ChoiceIdentity,
    MatrixRow,
    MatrixRowIdentity,
    Question,
    QuestionChoice,
    QuestionIdentity,
    Section,
    SurveyVersion,
)
from .drafting import (
    _bump_revision,
    _lock_version,
    _version_question_identities,
)


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
    question = Question.objects.create(
        section=section,
        identity=identity,
        type=question_type,
        prompt='Untitled question',
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
    clone = Question.objects.create(
        section=section,
        identity=identity,
        type=original.type,
        prompt=original.prompt,
        help_text=original.help_text,
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

    The snapshot row carries the label and its identity carries the live order, so
    reordering an option writes one row on each side and no position ever has to be
    parked out of the way first.
    """
    existing = {
        str(row.identity_id): row
        for row in manager.select_related('identity')
    }
    planned, claimed = _plan_label_sync(existing, labels, identity_ids)

    for identity_id, row in existing.items():
        if identity_id not in claimed:
            row.delete()

    survey = question.section.version.survey
    for index, (identity_id, label) in enumerate(planned, 1):
        if identity_id:
            row = existing[identity_id]
            row.label = label
            row.save(update_fields=('label',))
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
