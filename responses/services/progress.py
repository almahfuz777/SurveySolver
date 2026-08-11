"""Saving partial progress and committing a finished response."""

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone


from surveys.branching import Action
from surveys.models import (
    Question,
    Survey,
)
from surveys.presentation import (
    presentation_question,
    presented_question_ids,
)

from ..models import Answer, Submission
from .errors import (
    DuplicateSubmission,
    ResponseUnavailable,
    ResponseValidationError,
)
from .answers import _branch_matches, normalize_answer
from .eligibility import _ensure_account_access, _ensure_quota_available
from .submissions import can_access_submission


def _completion_answers(submission, data):
    sections_by_id = {
        str(section.id): section
        for section in submission.version.sections.all()
    }
    questions_by_id = {
        str(question.id): question
        for question in Question.objects.filter(section__version=submission.version)
        .prefetch_related('choices', 'matrix_rows')
    }
    presented_sections = submission.presentation.get('sections', [])
    section_positions = {
        section_data['id']: index
        for index, section_data in enumerate(presented_sections)
    }
    rules_by_section = {}
    for rule in submission.presentation.get('branch_rules', []):
        rules_by_section.setdefault(rule['source_section_id'], []).append(rule)

    answers = []
    errors = {}
    position = 0
    visited = set()
    while position < len(presented_sections):
        section_data = presented_sections[position]
        section_id = section_data['id']
        section = sections_by_id.get(section_id)
        if section is None:
            position += 1
            continue
        if section_id in visited:
            errors['submission'] = 'The survey logic could not determine a valid route.'
            break
        visited.add(section_id)
        section_values = {}
        for question_data in section_data.get('questions', []):
            question = questions_by_id.get(question_data['id'])
            if question is None:
                continue
            try:
                value = normalize_answer(
                    question,
                    data,
                    presentation_data=question_data,
                )
            except ValueError as error:
                errors[str(question.id)] = str(error)
                value = None
            else:
                if value is not None:
                    answers.append(Answer(submission=submission, question=question, value=value))
            section_values[str(question.id)] = value

        next_position = position + 1
        for rule in rules_by_section.get(section_id, []):
            if not _branch_matches(
                rule,
                section_values.get(rule['source_question_id']),
            ):
                continue
            if rule['action'] == Action.END_SURVEY:
                return answers, errors
            next_position = section_positions.get(
                rule['target_section_id'],
                len(presented_sections),
            )
            break
        position = next_position
    return answers, errors


@transaction.atomic
def save_progress(submission_id, user, session_key, data):
    submission = (
        Submission.objects.select_for_update()
        .select_related('survey', 'version')
        .get(pk=submission_id)
    )
    if not can_access_submission(submission, user, session_key):
        raise PermissionDenied
    _ensure_account_access(submission.survey, user)
    if submission.status == Submission.Status.COMPLETED:
        raise ResponseValidationError({'submission': 'Completed responses cannot be changed.'})

    question_ids = presented_question_ids(submission.presentation)
    questions = list(
        Question.objects.filter(id__in=question_ids, section__version=submission.version)
        .select_related('section')
        .prefetch_related('choices', 'matrix_rows')
    )
    questions_by_id = {str(question.id): question for question in questions}
    errors = {}
    values = {}
    for question_id in question_ids:
        question = questions_by_id.get(question_id)
        if question is None:
            continue
        try:
            values[question] = normalize_answer(
                question,
                data,
                enforce_required=False,
                presentation_data=presentation_question(
                    submission.presentation,
                    question.id,
                ),
            )
        except ValueError as error:
            errors[str(question.id)] = str(error)
    if errors:
        raise ResponseValidationError(errors)

    for question, value in values.items():
        if value is None:
            Answer.objects.filter(submission=submission, question=question).delete()
        else:
            Answer.objects.update_or_create(
                submission=submission,
                question=question,
                defaults={'value': value},
            )
    submission.save(update_fields=('updated_at',))
    return submission


@transaction.atomic
def complete_submission(submission_id, user, session_key, data):
    submission = (
        Submission.objects.select_for_update()
        .select_related('survey', 'version')
        .get(pk=submission_id)
    )
    if not can_access_submission(submission, user, session_key):
        raise PermissionDenied
    _ensure_account_access(submission.survey, user)
    if submission.status == Submission.Status.COMPLETED:
        return submission

    survey = Survey.objects.select_for_update().get(pk=submission.survey_id)
    if survey.status != Survey.Status.PUBLISHED:
        raise ResponseUnavailable('This survey is not accepting responses.')
    duplicate_filter = Q(session_key_hash=submission.session_key_hash)
    if submission.respondent_id:
        duplicate_filter |= Q(respondent_id=submission.respondent_id)
    duplicate = Submission.objects.filter(
        duplicate_filter,
        survey_id=submission.survey_id,
        status=Submission.Status.COMPLETED,
    ).exclude(pk=submission.pk).first()
    if duplicate:
        raise DuplicateSubmission(duplicate)
    _ensure_quota_available(survey, submission.version)

    answers, errors = _completion_answers(submission, data)
    if errors:
        raise ResponseValidationError(errors)

    submission.answers.all().delete()
    Answer.objects.bulk_create(answers)
    submission.status = Submission.Status.COMPLETED
    submission.completed_at = timezone.now()
    submission.save(update_fields=('status', 'completed_at', 'updated_at'))
    return submission
