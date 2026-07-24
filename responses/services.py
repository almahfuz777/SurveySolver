from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.signing import salted_hmac
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.core.validators import validate_email

from accounts.models import Profile
from django_countries import countries

from surveys.models import (
    BranchRule,
    Question,
    Survey,
    SurveyEligibilityCriteria,
    SurveyVersion,
)
from surveys.presentation import (
    build_submission_presentation,
    presentation_question,
    presented_question_ids,
)

from .models import Answer, Submission


class ResponseUnavailable(Exception):
    pass


class ResponseValidationError(Exception):
    def __init__(self, errors):
        self.errors = errors
        super().__init__('Some answers need attention.')


class DuplicateSubmission(Exception):
    def __init__(self, submission):
        self.submission = submission
        super().__init__('A response has already been completed for this survey.')


class EligibilityUnknown(Exception):
    pass


class IneligibleRespondent(Exception):
    pass


class QuotaReached(Exception):
    pass


def hash_session_key(session_key):
    return salted_hmac('responses.session', session_key, algorithm='sha256').hexdigest()


def current_published_version(survey, invitation_access=False):
    if survey.status != Survey.Status.PUBLISHED:
        raise ResponseUnavailable('This survey is not accepting responses.')
    if survey.visibility == Survey.Visibility.INVITATION_ONLY and not invitation_access:
        raise ResponseUnavailable('This survey requires an invitation.')
    try:
        return survey.versions.get(status=SurveyVersion.Status.PUBLISHED)
    except SurveyVersion.DoesNotExist as error:
        raise ResponseUnavailable('This survey is not accepting responses.') from error


def build_presentation(version):
    return build_submission_presentation(version)


def _validated_identity(survey, consent, identity_data):
    if survey.identity_mode == Survey.IdentityMode.ANONYMOUS:
        return {}, None
    identity_data = identity_data or {}
    name = identity_data.get('name', '').strip()
    email = identity_data.get('email', '').strip().casefold()
    errors = {}
    if not consent:
        errors['identity_consent'] = 'Consent is required for an identified response.'
    if not name:
        errors['identity_name'] = 'Enter the name that will be shared with the researcher.'
    try:
        validate_email(email)
    except ValidationError:
        errors['identity_email'] = 'Enter a valid email address.'
    if errors:
        raise ResponseValidationError(errors)
    return {'name': name, 'email': email}, timezone.now()


def _current_age(birth_date):
    today = timezone.localdate()
    return today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )


def _eligibility_values(criteria, user, screener_data):
    targeted_fields = {
        'birth_date': criteria.min_age is not None or criteria.max_age is not None,
        'education_level': bool(criteria.education_levels),
        'country': bool(criteria.countries),
        'gender': bool(criteria.genders),
        'employment_status': bool(criteria.employment_statuses),
    }
    if user and user.is_authenticated:
        profile = user.profile
        values = {
            'birth_date': profile.birth_date,
            'education_level': profile.education_level,
            'country': profile.country.code if profile.country else '',
            'gender': profile.gender,
            'employment_status': profile.employment_status,
        }
        missing = [field for field, required in targeted_fields.items() if required and not values[field]]
        if missing:
            raise EligibilityUnknown('Complete the required research profile fields to continue.')
        return values

    screener_data = screener_data or {}
    values = {}
    errors = {}
    if targeted_fields['birth_date']:
        try:
            values['birth_date'] = date.fromisoformat(screener_data.get('birth_date', ''))
        except (TypeError, ValueError):
            errors['eligibility_birth_date'] = 'Enter a valid date of birth.'
    for field, allowed, error_message in (
        ('education_level', set(Profile.EducationLevel.values), 'Select your education level.'),
        ('gender', set(Profile.Gender.values), 'Select your gender.'),
        ('employment_status', set(Profile.EmploymentStatus.values), 'Select your employment status.'),
    ):
        if targeted_fields[field]:
            value = screener_data.get(field, '')
            if value not in allowed:
                errors[f'eligibility_{field}'] = error_message
            else:
                values[field] = value
    if targeted_fields['country']:
        value = screener_data.get('country', '')
        if value not in {code for code, _ in countries}:
            errors['eligibility_country'] = 'Select your country.'
        else:
            values['country'] = value
    if errors:
        raise ResponseValidationError(errors)
    return values


def _validated_eligibility(survey, user, screener_data):
    try:
        criteria = survey.eligibility_criteria
    except SurveyEligibilityCriteria.DoesNotExist:
        return {'targeted': False}, timezone.now()
    if not criteria.is_targeted:
        return {'targeted': False}, timezone.now()
    values = _eligibility_values(criteria, user, screener_data)
    age = _current_age(values['birth_date']) if values.get('birth_date') else None
    eligible = (
        (criteria.min_age is None or age >= criteria.min_age)
        and (criteria.max_age is None or age <= criteria.max_age)
        and (not criteria.education_levels or values['education_level'] in criteria.education_levels)
        and (not criteria.countries or values['country'] in criteria.countries)
        and (not criteria.genders or values['gender'] in criteria.genders)
        and (
            not criteria.employment_statuses
            or values['employment_status'] in criteria.employment_statuses
        )
    )
    if not eligible:
        raise IneligibleRespondent('Your screener does not match this study’s eligibility criteria.')
    snapshot = {
        key: value.isoformat() if isinstance(value, date) else value
        for key, value in values.items()
    }
    snapshot['targeted'] = True
    return snapshot, timezone.now()


def _ensure_quota_available(survey, version):
    if survey.response_limit is None:
        return
    completed = survey.submissions.filter(status=Submission.Status.COMPLETED).count()
    if completed >= survey.response_limit:
        raise QuotaReached('This survey has reached its response limit.')


@transaction.atomic
def start_submission(
    survey,
    user,
    session_key,
    source=Submission.Source.DIRECT,
    identity_consent=False,
    identity_data=None,
    screener_data=None,
    respondent_invitation_id=None,
):
    from sharing.respondent_invitations import (
        bind_respondent_invitation,
        lock_respondent_invitation,
    )

    survey = Survey.objects.select_for_update().get(pk=survey.pk)
    invitation = None
    if respondent_invitation_id:
        invitation = lock_respondent_invitation(respondent_invitation_id, survey.id)
    version = current_published_version(survey, invitation_access=bool(invitation))
    session_hash = hash_session_key(session_key)
    respondent = user if user and user.is_authenticated else None
    if invitation and invitation.bound_submission_id:
        bound_submission = Submission.objects.filter(
            id=invitation.bound_submission_id,
            survey=survey,
        ).first()
        if bound_submission and can_access_submission(bound_submission, user, session_key):
            return bound_submission
        raise PermissionDenied('This respondent invitation has already been used.')
    in_progress_filter = Q(session_key_hash=session_hash)
    if respondent:
        in_progress_filter |= Q(respondent=respondent)
    existing = Submission.objects.filter(
        in_progress_filter,
        survey=survey,
        version=version,
        status=Submission.Status.IN_PROGRESS,
    ).first()
    if existing:
        if invitation:
            if existing.source != Submission.Source.INVITATION:
                existing.source = Submission.Source.INVITATION
                existing.save(update_fields=('source', 'updated_at'))
            bind_respondent_invitation(invitation, existing)
        return existing
    completed_filter = Q(session_key_hash=session_hash)
    if respondent:
        completed_filter |= Q(respondent=respondent)
    completed = Submission.objects.filter(
        completed_filter,
        survey=survey,
        status=Submission.Status.COMPLETED,
    ).first()
    if completed:
        return completed
    _ensure_quota_available(survey, version)
    eligibility_data, eligibility_checked_at = _validated_eligibility(
        survey,
        respondent,
        screener_data,
    )
    identity_data, identity_consent_at = _validated_identity(
        survey,
        identity_consent,
        identity_data,
    )
    submission = Submission.objects.create(
        survey=survey,
        version=version,
        respondent=respondent,
        session_key_hash=session_hash,
        source=(Submission.Source.INVITATION if invitation else source),
        presentation=build_presentation(version),
        identity_mode_snapshot=survey.identity_mode,
        identity_data=identity_data,
        identity_consent_at=identity_consent_at,
        is_eligible=True,
        eligibility_data=eligibility_data,
        eligibility_checked_at=eligibility_checked_at,
    )
    SurveyVersion.objects.filter(pk=version.pk, has_response_history=False).update(
        has_response_history=True,
    )
    if invitation:
        bind_respondent_invitation(invitation, submission)
    return submission


def can_access_submission(submission, user, session_key):
    if submission.session_key_hash == hash_session_key(session_key):
        return True
    return bool(
        user
        and user.is_authenticated
        and submission.respondent_id
        and submission.respondent_id == user.id
    )


def resumable_submissions(user, session_key):
    access_filters = []
    if session_key:
        access_filters.append(
            Q(session_key_hash=hash_session_key(session_key)),
        )
    if user and user.is_authenticated:
        access_filters.append(Q(respondent=user))
    if not access_filters:
        return Submission.objects.none()

    access_filter = access_filters[0]
    for condition in access_filters[1:]:
        access_filter |= condition
    return (
        Submission.objects.filter(
            access_filter,
            status=Submission.Status.IN_PROGRESS,
            survey__deleted_at__isnull=True,
        )
        .select_related('survey', 'version')
        .prefetch_related('survey__topics')
        .annotate(saved_answer_count=Count('answers', distinct=True))
        .order_by('-updated_at')
        .distinct()
    )


@transaction.atomic
def discard_in_progress_submission(submission_id, user, session_key):
    submission = (
        Submission.objects.select_for_update()
        .select_related('survey')
        .get(
            pk=submission_id,
            status=Submission.Status.IN_PROGRESS,
        )
    )
    if not can_access_submission(submission, user, session_key):
        raise PermissionDenied
    survey_title = submission.survey.title
    submission.delete()
    return survey_title


def _empty(value):
    return value is None or value == '' or value == [] or value == {}


def _choice_map(question, allowed_ids=None):
    allowed_ids = set(allowed_ids or ())
    return {
        str(choice.id): choice.label
        for choice in question.choices.all()
        if not allowed_ids or str(choice.id) in allowed_ids
    }


def _selected_choice(question, raw_value, allowed_ids=None):
    choices = _choice_map(question, allowed_ids)
    if raw_value not in choices:
        raise ValueError('Select one of the available options.')
    return {'choice_id': raw_value, 'label': choices[raw_value]}


def normalize_answer(
    question,
    data,
    enforce_required=True,
    presentation_data=None,
):
    name = f'q_{question.id}'
    raw_value = data.get(name)
    if question.type in {Question.Type.MULTIPLE_CHOICE, Question.Type.RANKING}:
        raw_value = [value for value in data.getlist(name) if value]
    elif question.type == Question.Type.LIKERT_MATRIX:
        presented_rows = (
            presentation_data.get('rows', [])
            if presentation_data is not None
            else [str(row.id) for row in question.matrix_rows.all()]
        )
        raw_value = {
            row_id: data.get(f'{name}_{row_id}', '')
            for row_id in presented_rows
            if data.get(f'{name}_{row_id}', '')
        }

    required = (
        presentation_data.get('required', False)
        if presentation_data is not None
        else question.required
    )
    if _empty(raw_value):
        if required and enforce_required:
            raise ValueError('This question is required.')
        return None

    config = question.config
    if question.type in {Question.Type.SHORT_TEXT, Question.Type.LONG_TEXT}:
        value = raw_value.strip()
        minimum = config.get('min_length')
        maximum = config.get('max_length')
        if minimum is not None and len(value) < minimum:
            raise ValueError(f'Enter at least {minimum} characters.')
        if maximum is not None and len(value) > maximum:
            raise ValueError(f'Enter no more than {maximum} characters.')
        return value
    if question.type == Question.Type.NUMBER:
        try:
            number = Decimal(raw_value)
        except (InvalidOperation, TypeError):
            raise ValueError('Enter a valid number.') from None
        if not number.is_finite():
            raise ValueError('Enter a finite number.')
        minimum = config.get('min_value')
        maximum = config.get('max_value')
        if minimum is not None and number < Decimal(str(minimum)):
            raise ValueError(f'Enter a value of at least {minimum}.')
        if maximum is not None and number > Decimal(str(maximum)):
            raise ValueError(f'Enter a value no greater than {maximum}.')
        return str(number)
    if question.type == Question.Type.DATE:
        try:
            return date.fromisoformat(raw_value).isoformat()
        except (TypeError, ValueError):
            raise ValueError('Enter a valid date.') from None
    if question.type in {Question.Type.SINGLE_CHOICE, Question.Type.DROPDOWN}:
        return _selected_choice(
            question,
            raw_value,
            presentation_data.get('choices') if presentation_data else None,
        )
    if question.type == Question.Type.MULTIPLE_CHOICE:
        if len(raw_value) != len(set(raw_value)):
            raise ValueError('Select each option only once.')
        return [
            _selected_choice(
                question,
                value,
                presentation_data.get('choices') if presentation_data else None,
            )
            for value in raw_value
        ]
    if question.type == Question.Type.RANKING:
        choices = _choice_map(
            question,
            presentation_data.get('choices') if presentation_data else None,
        )
        if len(raw_value) != len(choices) or set(raw_value) != set(choices):
            raise ValueError('Rank every option exactly once.')
        return [
            _selected_choice(question, value, choices)
            for value in raw_value
        ]
    if question.type == Question.Type.SCALE:
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            raise ValueError('Select a valid scale value.') from None
        minimum = int(config.get('scale_min', 1))
        maximum = int(config.get('scale_max', 5))
        if value < minimum or value > maximum:
            raise ValueError(f'Select a value from {minimum} to {maximum}.')
        return value
    if question.type == Question.Type.LIKERT_MATRIX:
        choices = _choice_map(
            question,
            presentation_data.get('choices') if presentation_data else None,
        )
        allowed_rows = set(presentation_data.get('rows', [])) if presentation_data else set()
        rows = {
            str(row.id): row.label
            for row in question.matrix_rows.all()
            if not allowed_rows or str(row.id) in allowed_rows
        }
        if required and set(raw_value) != set(rows):
            raise ValueError('Answer every statement in this matrix.')
        if not set(raw_value).issubset(rows):
            raise ValueError('The matrix response contains an invalid statement.')
        normalized = {}
        for row_id, choice_id in raw_value.items():
            if choice_id not in choices:
                raise ValueError('Select an available response for every statement.')
            normalized[row_id] = {
                'row_label': rows[row_id],
                'choice_id': choice_id,
                'choice_label': choices[choice_id],
            }
        return normalized
    raise ValueError('This question type is not supported.')


def _branch_values(value):
    if value is None:
        return []
    if isinstance(value, dict):
        if 'choice_id' in value:
            return [value['choice_id'], value['label']]
        values = []
        for row_value in value.values():
            values.extend((row_value['choice_id'], row_value['choice_label']))
        return values
    if isinstance(value, list):
        values = []
        for choice in value:
            values.extend((choice['choice_id'], choice['label']))
        return values
    return [str(value)]


def _branch_matches(rule, value):
    operator = rule['operator'] if isinstance(rule, dict) else rule.operator
    compare = (
        rule.get('compare_value', '')
        if isinstance(rule, dict)
        else rule.compare_value
    )
    if operator == BranchRule.Operator.ANSWERED:
        return bool(_branch_values(value))
    compare_value = compare.strip().casefold()
    values = [str(item).strip().casefold() for item in _branch_values(value)]
    if operator == BranchRule.Operator.EQUALS:
        return compare_value in values
    if operator == BranchRule.Operator.NOT_EQUALS:
        return bool(values) and compare_value not in values
    if operator == BranchRule.Operator.CONTAINS:
        return any(compare_value in item for item in values)
    return False


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
            if rule['action'] == BranchRule.Action.END_SURVEY:
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
