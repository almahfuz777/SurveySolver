from copy import deepcopy

from django.db import models, transaction
from django.db.models import Max
from django.utils import timezone

from sharing.permissions import EDIT_ROLES, accessible_surveys

from .branching import Action
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
    SurveyVersion,
)
from .presentation import (
    content_changed,
    resolved_branch_rules,
    resolved_version,
)


class PublicationError(Exception):
    def __init__(self, errors):
        self.errors = errors
        super().__init__('Survey is not ready to publish.')


def readiness_errors(version):
    errors = []
    sections = resolved_version(version)
    questions = [
        question
        for section in sections
        for question in section.questions.all()
    ]
    if not questions:
        errors.append('Add at least one question.')
    for question in questions:
        if question.accepts_choices and len(question.choices.all()) < 2:
            errors.append(f'“{question.prompt}” needs at least two choices.')
        if question.uses_matrix_rows and len(question.matrix_rows.all()) < 2:
            errors.append(f'“{question.prompt}” needs at least two matrix statements.')

    cycle_sections = branch_cycle_sections(version)
    if cycle_sections:
        titles = [
            section.title
            for section in sections
            if str(section.id) in cycle_sections
        ]
        errors.append(
            'Branch rules loop between sections (' + ' ↔ '.join(titles) + '), '
            'so respondents can never reach the end. Point one of these rules at a '
            'later section or “End survey”.'
        )
    return errors


def branch_cycle_sections(version):
    """Return snapshot section IDs that participate in a resolved live-rule loop."""

    edges = {}
    for rule in resolved_branch_rules(version):
        if (
            rule['action'] == Action.GO_TO_SECTION
            and rule['target_section_id']
        ):
            edges.setdefault(rule['source_section_id'], set()).add(
                rule['target_section_id']
            )

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


def _clone_version(source, created_by, *, number=None):
    if number is None:
        number = (
            source.survey.versions.aggregate(max_number=Max('number'))['max_number']
            or 0
        ) + 1
    clone = SurveyVersion.objects.create(
        survey=source.survey,
        number=number,
        created_by=created_by,
    )
    section_map = {}
    for section in source.sections.select_related('identity').order_by('order'):
        cloned_section = Section.objects.create(
            version=clone,
            identity=section.identity,
            title=section.title,
            description=section.description,
            order=section.order,
            randomize_questions=section.randomize_questions,
        )
        section_map[section.id] = cloned_section
        for question in section.questions.select_related('identity').order_by('order'):
            cloned_question = Question.objects.create(
                section=cloned_section,
                identity=question.identity,
                type=question.type,
                prompt=question.prompt,
                help_text=question.help_text,
                required=question.required,
                randomize_choices=question.randomize_choices,
                order=question.order,
                config=deepcopy(question.config),
            )
            QuestionChoice.objects.bulk_create(
                [
                    QuestionChoice(
                        question=cloned_question,
                        identity=choice.identity,
                        label=choice.label,
                        order=choice.order,
                    )
                    for choice in question.choices.select_related('identity').all()
                ]
            )
            MatrixRow.objects.bulk_create(
                [
                    MatrixRow(
                        question=cloned_question,
                        identity=row.identity,
                        label=row.label,
                        order=row.order,
                    )
                    for row in question.matrix_rows.select_related('identity').all()
                ]
            )

    return clone


def prune_orphan_presentation(survey):
    """Drop live-layer rows left dangling after a draft is deleted.

    Deleting a draft removes its snapshot rows but not the survey-owned identity
    rows or the survey-level branch rules that referenced draft-only content.
    Any identity with no surviving snapshot (and any branch rule pointing at
    one) can never resolve again, so remove them. Branch rules go first because
    the identities they reference are PROTECTed.
    """
    orphan_sections = SectionIdentity.objects.filter(survey=survey, snapshots__isnull=True)
    orphan_questions = QuestionIdentity.objects.filter(survey=survey, snapshots__isnull=True)
    orphan_choices = ChoiceIdentity.objects.filter(survey=survey, snapshots__isnull=True)
    orphan_rows = MatrixRowIdentity.objects.filter(survey=survey, snapshots__isnull=True)

    SurveyBranchRule.objects.filter(survey=survey).filter(
        models.Q(source_question_identity__in=orphan_questions)
        | models.Q(target_section_identity__in=orphan_sections)
        | models.Q(compare_choice_identity__in=orphan_choices)
    ).delete()

    # Leaf identities first so their PROTECT references are gone before the
    # question/section identities they hang off are removed.
    orphan_choices.delete()
    orphan_rows.delete()
    orphan_questions.delete()
    orphan_sections.delete()


def publication_intent(survey, draft=None):
    draft = draft or survey.draft_version
    active = survey.versions.filter(status=SurveyVersion.Status.PUBLISHED).first()
    if active is None:
        return {
            'action': 'initial',
            'version_number': draft.number,
            'label': f'Publish survey as version {draft.number}?',
            'can_publish': True,
            'has_active': False,
            'has_draft_changes': False,
        }
    changed = content_changed(draft, active)
    if not changed:
        return {
            'action': 'unchanged',
            'version_number': active.number,
            'label': 'No questionnaire changes to publish',
            'can_publish': False,
            'has_active': True,
            'has_draft_changes': False,
        }
    if not active.has_response_history:
        return {
            'action': 'replace',
            'version_number': active.number,
            'label': f'Update version {active.number}?',
            'can_publish': True,
            'has_active': True,
            'has_draft_changes': True,
        }
    return {
        'action': 'new',
        'version_number': draft.number,
        'label': f'Publish new version {draft.number}?',
        'can_publish': True,
        'has_active': True,
        'has_draft_changes': True,
    }


@transaction.atomic
def publish_survey(survey_id, user, expected_revision):
    survey = accessible_surveys(user, EDIT_ROLES).select_for_update().get(id=survey_id)
    if survey.status == Survey.Status.ARCHIVED:
        raise PublicationError(['Archived surveys cannot be published.'])
    draft = SurveyVersion.objects.select_for_update().get(
        survey=survey,
        status=SurveyVersion.Status.DRAFT,
    )
    if draft.revision != expected_revision:
        from .services import StaleVersionError

        raise StaleVersionError
    errors = readiness_errors(draft)
    if errors:
        raise PublicationError(errors)

    active = (
        SurveyVersion.objects.select_for_update()
        .filter(survey=survey, status=SurveyVersion.Status.PUBLISHED)
        .first()
    )
    intent = publication_intent(survey, draft)
    if not intent['can_publish']:
        raise PublicationError(['There are no questionnaire changes to publish.'])

    if active is not None:
        if active.has_response_history or active.submissions.exists():
            SurveyVersion.objects.filter(pk=active.pk).update(
                status=SurveyVersion.Status.RETIRED,
            )
        else:
            active_number = active.number
            SurveyVersion.objects.filter(pk=active.pk).delete()
            draft.number = active_number

    now = timezone.now()
    draft.status = SurveyVersion.Status.PUBLISHED
    draft.title_snapshot = survey.title
    draft.published_at = now
    draft.save(
        update_fields=(
            'number',
            'status',
            'title_snapshot',
            'published_at',
            'updated_at',
        )
    )
    survey.status = Survey.Status.PUBLISHED
    survey.published_at = now
    survey.closed_at = None
    survey.save(update_fields=('status', 'published_at', 'closed_at', 'updated_at'))
    next_draft = _clone_version(draft, user)
    return draft, next_draft


@transaction.atomic
def restore_version_to_draft(survey_id, version_id, user, expected_revision):
    survey = accessible_surveys(user, {'owner'}).select_for_update().get(id=survey_id)
    source = SurveyVersion.objects.select_for_update().get(
        pk=version_id,
        survey=survey,
        status=SurveyVersion.Status.RETIRED,
    )
    draft = SurveyVersion.objects.select_for_update().get(
        survey=survey,
        status=SurveyVersion.Status.DRAFT,
    )
    if draft.revision != expected_revision:
        from .services import StaleVersionError

        raise StaleVersionError
    draft.delete()
    restored = _clone_version(source, user)
    prune_orphan_presentation(survey)
    return source, restored


@transaction.atomic
def discard_draft_changes(survey_id, user, expected_revision):
    """Throw away the working draft and re-fork it from the live version."""
    survey = accessible_surveys(user, EDIT_ROLES).select_for_update().get(id=survey_id)
    active = (
        SurveyVersion.objects.select_for_update()
        .filter(survey=survey, status=SurveyVersion.Status.PUBLISHED)
        .first()
    )
    if active is None:
        raise PublicationError(['There is no published version to reset to.'])
    draft = SurveyVersion.objects.select_for_update().get(
        survey=survey,
        status=SurveyVersion.Status.DRAFT,
    )
    if draft.revision != expected_revision:
        from .services import StaleVersionError

        raise StaleVersionError
    draft.delete()
    new_draft = _clone_version(active, user)
    prune_orphan_presentation(survey)
    return new_draft


@transaction.atomic
def delete_retired_version(survey_id, version_id, user):
    from responses.deletion import purge_version_responses

    survey = accessible_surveys(user, {'owner'}).select_for_update().get(id=survey_id)
    version = SurveyVersion.objects.select_for_update().get(
        pk=version_id,
        survey=survey,
        status=SurveyVersion.Status.RETIRED,
    )
    response_count = purge_version_responses(version, user)
    SurveyVersion.objects.filter(pk=version.pk).delete()
    return response_count
