import random
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.signing import salted_hmac
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.core.validators import validate_email

from accounts.models import Profile
from django_countries import countries

from surveys.models import BranchRule, EligibilityCriteria, Question, Survey, SurveyVersion

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


def hash_session_key(session_key):
    return salted_hmac('responses.session', session_key, algorithm='sha256').hexdigest()


def current_published_version(survey):
    if survey.status != Survey.Status.PUBLISHED:
        raise ResponseUnavailable('This survey is not accepting responses.')
    if survey.visibility == Survey.Visibility.INVITATION_ONLY:
        raise ResponseUnavailable('This survey requires an invitation.')
    try:
        return survey.versions.get(status=SurveyVersion.Status.PUBLISHED)
    except SurveyVersion.DoesNotExist as error:
        raise ResponseUnavailable('This survey is not accepting responses.') from error


def build_presentation(version):
    generator = random.SystemRandom()
    sections = []
    for section in version.sections.prefetch_related('questions__choices', 'questions__matrix_rows'):
        questions = list(section.questions.all())
        if section.randomize_questions:
            generator.shuffle(questions)
        question_data = []
        for question in questions:
            choices = list(question.choices.all())
            if question.randomize_choices:
                generator.shuffle(choices)
            question_data.append(
                {
                    'id': str(question.id),
                    'choices': [str(choice.id) for choice in choices],
                    'rows': [str(row.id) for row in question.matrix_rows.all()],
                }
            )
        sections.append({'id': str(section.id), 'questions': question_data})
    return {'sections': sections}


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


def _validated_eligibility(version, user, screener_data):
    try:
        criteria = version.eligibility_criteria
    except EligibilityCriteria.DoesNotExist:
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


@transaction.atomic
def start_submission(
    survey,
    user,
    session_key,
    source=Submission.Source.DIRECT,
    identity_consent=False,
    identity_data=None,
    screener_data=None,
):
    survey = Survey.objects.select_for_update().get(pk=survey.pk)
    version = current_published_version(survey)
    session_hash = hash_session_key(session_key)
    respondent = user if user and user.is_authenticated else None
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
    eligibility_data, eligibility_checked_at = _validated_eligibility(
        version,
        respondent,
        screener_data,
    )
    identity_data, identity_consent_at = _validated_identity(
        survey,
        identity_consent,
        identity_data,
    )
    return Submission.objects.create(
        survey=survey,
        version=version,
        respondent=respondent,
        session_key_hash=session_hash,
        source=source,
        presentation=build_presentation(version),
        identity_data=identity_data,
        identity_consent_at=identity_consent_at,
        is_eligible=True,
        eligibility_data=eligibility_data,
        eligibility_checked_at=eligibility_checked_at,
    )


def can_access_submission(submission, user, session_key):
    if submission.session_key_hash == hash_session_key(session_key):
        return True
    return bool(
        user
        and user.is_authenticated
        and submission.respondent_id
        and submission.respondent_id == user.id
    )


def _empty(value):
    return value is None or value == '' or value == [] or value == {}


def _choice_map(question):
    return {str(choice.id): choice.label for choice in question.choices.all()}


def _selected_choice(question, raw_value):
    choices = _choice_map(question)
    if raw_value not in choices:
        raise ValueError('Select one of the available options.')
    return {'choice_id': raw_value, 'label': choices[raw_value]}


def normalize_answer(question, data, enforce_required=True):
    name = f'q_{question.id}'
    raw_value = data.get(name)
    if question.type in {Question.Type.MULTIPLE_CHOICE, Question.Type.RANKING}:
        raw_value = [value for value in data.getlist(name) if value]
    elif question.type == Question.Type.LIKERT_MATRIX:
        raw_value = {
            str(row.id): data.get(f'{name}_{row.id}', '')
            for row in question.matrix_rows.all()
            if data.get(f'{name}_{row.id}', '')
        }

    if _empty(raw_value):
        if question.required and enforce_required:
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
        return _selected_choice(question, raw_value)
    if question.type == Question.Type.MULTIPLE_CHOICE:
        if len(raw_value) != len(set(raw_value)):
            raise ValueError('Select each option only once.')
        return [_selected_choice(question, value) for value in raw_value]
    if question.type == Question.Type.RANKING:
        choices = _choice_map(question)
        if len(raw_value) != len(choices) or set(raw_value) != set(choices):
            raise ValueError('Rank every option exactly once.')
        return [_selected_choice(question, value) for value in raw_value]
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
        choices = _choice_map(question)
        rows = {str(row.id): row.label for row in question.matrix_rows.all()}
        if question.required and set(raw_value) != set(rows):
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
    if rule.operator == BranchRule.Operator.ANSWERED:
        return bool(_branch_values(value))
    compare_value = rule.compare_value.strip().casefold()
    values = [str(item).strip().casefold() for item in _branch_values(value)]
    if rule.operator == BranchRule.Operator.EQUALS:
        return compare_value in values
    if rule.operator == BranchRule.Operator.NOT_EQUALS:
        return bool(values) and compare_value not in values
    if rule.operator == BranchRule.Operator.CONTAINS:
        return any(compare_value in item for item in values)
    return False


def _completion_answers(submission, data):
    sections = list(
        submission.version.sections.prefetch_related(
            'questions__choices',
            'questions__matrix_rows',
        ).order_by('order')
    )
    section_positions = {section.id: index for index, section in enumerate(sections)}
    rules_by_section = {}
    for rule in submission.version.branch_rules.select_related(
        'source_question__section',
        'target_section',
    ).order_by('order'):
        rules_by_section.setdefault(rule.source_question.section_id, []).append(rule)

    answers = []
    errors = {}
    position = 0
    visited = set()
    while position < len(sections):
        section = sections[position]
        if section.id in visited:
            errors['submission'] = 'The survey logic could not determine a valid route.'
            break
        visited.add(section.id)
        section_values = {}
        for question in section.questions.all():
            try:
                value = normalize_answer(question, data)
            except ValueError as error:
                errors[str(question.id)] = str(error)
                value = None
            else:
                if value is not None:
                    answers.append(Answer(submission=submission, question=question, value=value))
            section_values[question.id] = value

        next_position = position + 1
        for rule in rules_by_section.get(section.id, []):
            if not _branch_matches(rule, section_values.get(rule.source_question_id)):
                continue
            if rule.action == BranchRule.Action.END_SURVEY:
                return answers, errors
            next_position = section_positions.get(rule.target_section_id, len(sections))
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

    questions = list(
        Question.objects.filter(section__version=submission.version)
        .select_related('section')
        .prefetch_related('choices', 'matrix_rows')
        .order_by('section__order', 'order')
    )
    errors = {}
    values = {}
    for question in questions:
        try:
            values[question] = normalize_answer(question, data, enforce_required=False)
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

    Survey.objects.select_for_update().get(pk=submission.survey_id)
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

    answers, errors = _completion_answers(submission, data)
    if errors:
        raise ResponseValidationError(errors)

    submission.answers.all().delete()
    Answer.objects.bulk_create(answers)
    submission.status = Submission.Status.COMPLETED
    submission.completed_at = timezone.now()
    submission.save(update_fields=('status', 'completed_at', 'updated_at'))
    return submission
