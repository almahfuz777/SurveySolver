from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from django_countries import countries

from accounts.models import Profile
from surveys.models import Survey

from .models import Submission
from .services import (
    DuplicateSubmission,
    EligibilityUnknown,
    IneligibleRespondent,
    ResponseUnavailable,
    ResponseValidationError,
    can_access_submission,
    complete_submission,
    current_published_version,
    save_progress,
    start_submission,
)


def _session_key(request):
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def _public_survey(slug):
    survey = get_object_or_404(Survey.objects.prefetch_related('topics'), slug=slug)
    try:
        version = current_published_version(survey)
    except ResponseUnavailable as error:
        raise Http404(str(error)) from error
    return survey, version


@require_http_methods(['GET', 'POST'])
def survey_landing(request, slug):
    survey, version = _public_survey(slug)
    identity_errors = {}
    eligibility_notice = ''
    if request.method == 'POST':
        try:
            submission = start_submission(
                survey,
                request.user,
                _session_key(request),
                identity_consent=request.POST.get('identity_consent') == 'yes',
                identity_data={
                    'name': request.POST.get('identity_name', ''),
                    'email': request.POST.get('identity_email', ''),
                },
                screener_data={
                    'birth_date': request.POST.get('eligibility_birth_date', ''),
                    'education_level': request.POST.get('eligibility_education_level', ''),
                    'country': request.POST.get('eligibility_country', ''),
                    'gender': request.POST.get('eligibility_gender', ''),
                    'employment_status': request.POST.get('eligibility_employment_status', ''),
                },
            )
        except ResponseValidationError as error:
            identity_errors = error.errors
        except (EligibilityUnknown, IneligibleRespondent) as error:
            eligibility_notice = str(error)
        else:
            return redirect('response_form', submission_id=submission.id)
    default_name = request.user.get_full_name() if request.user.is_authenticated else ''
    default_email = request.user.email if request.user.is_authenticated else ''
    criteria = getattr(version, 'eligibility_criteria', None)
    return render(
        request,
        'responses/survey_landing.html',
        {
            'survey': survey,
            'version': version,
            'identity_errors': identity_errors,
            'identity_name': request.POST.get('identity_name', default_name),
            'identity_email': request.POST.get('identity_email', default_email),
            'criteria': criteria if criteria and criteria.is_targeted else None,
            'eligibility_errors': identity_errors,
            'eligibility_notice': eligibility_notice,
            'education_choices': Profile.EducationLevel.choices,
            'gender_choices': Profile.Gender.choices,
            'employment_choices': Profile.EmploymentStatus.choices,
            'country_choices': countries,
        },
        status=403 if eligibility_notice else (422 if identity_errors else 200),
    )


def _accessible_submission(request, submission_id):
    submission = get_object_or_404(
        Submission.objects.select_related('survey', 'version'),
        id=submission_id,
    )
    if not can_access_submission(submission, request.user, _session_key(request)):
        raise PermissionDenied
    return submission


def _presented_sections(submission, data=None, errors=None):
    errors = errors or {}
    sections = {
        str(section.id): section
        for section in submission.version.sections.prefetch_related(
            'questions__choices',
            'questions__matrix_rows',
        )
    }
    presented = []
    for section_data in submission.presentation.get('sections', []):
        section = sections.get(section_data['id'])
        if not section:
            continue
        questions = {str(question.id): question for question in section.questions.all()}
        items = []
        for question_data in section_data.get('questions', []):
            question = questions.get(question_data['id'])
            if not question:
                continue
            choices = {str(choice.id): choice for choice in question.choices.all()}
            rows = {str(row.id): row for row in question.matrix_rows.all()}
            name = f'q_{question.id}'
            selected_values = data.getlist(name) if data else []
            choice_items = [
                {
                    'choice': choices[choice_id],
                    'selected': choice_id in selected_values
                    or bool(data and data.get(name) == choice_id),
                }
                for choice_id in question_data.get('choices', [])
                if choice_id in choices
            ]
            row_items = []
            for row_id in question_data.get('rows', []):
                if row_id not in rows:
                    continue
                row_name = f'{name}_{row_id}'
                row_items.append(
                    {
                        'row': rows[row_id],
                        'name': row_name,
                        'choices': [
                            {
                                'choice': choice_item['choice'],
                                'selected': bool(
                                    data
                                    and data.get(row_name)
                                    == str(choice_item['choice'].id)
                                ),
                            }
                            for choice_item in choice_items
                        ],
                    }
                )
            ranking = []
            if question.type == question.Type.RANKING:
                for index in range(len(choice_items)):
                    ranking.append(
                        {
                            'position': index + 1,
                            'options': [
                                {
                                    'choice': choice_item['choice'],
                                    'selected': (
                                        index < len(selected_values)
                                        and selected_values[index]
                                        == str(choice_item['choice'].id)
                                    ),
                                }
                                for choice_item in choice_items
                            ],
                        }
                    )
            items.append(
                {
                    'question': question,
                    'name': name,
                    'value': data.get(name, '') if data else '',
                    'choices': choice_items,
                    'rows': row_items,
                    'ranking': ranking,
                    'scale_values': range(
                        int(question.config.get('scale_min', 1)),
                        int(question.config.get('scale_max', 5)) + 1,
                    ),
                    'error': errors.get(str(question.id)),
                }
            )
        presented.append({'section': section, 'items': items})
    return presented


def _saved_answer_data(submission):
    data = QueryDict('', mutable=True)
    for answer in submission.answers.select_related('question'):
        name = f'q_{answer.question_id}'
        value = answer.value
        if answer.question.type in {
            answer.question.Type.SINGLE_CHOICE,
            answer.question.Type.DROPDOWN,
        }:
            data[name] = value['choice_id']
        elif answer.question.type in {
            answer.question.Type.MULTIPLE_CHOICE,
            answer.question.Type.RANKING,
        }:
            data.setlist(name, [choice['choice_id'] for choice in value])
        elif answer.question.type == answer.question.Type.LIKERT_MATRIX:
            for row_id, row_value in value.items():
                data[f'{name}_{row_id}'] = row_value['choice_id']
        else:
            data[name] = str(value)
    return data


@require_http_methods(['GET', 'POST'])
def submission_form(request, submission_id):
    submission = _accessible_submission(request, submission_id)
    if submission.status == Submission.Status.COMPLETED:
        return redirect('response_complete', submission_id=submission.id)
    errors = {}
    if request.method == 'POST':
        try:
            if request.POST.get('action') == 'save':
                save_progress(
                    submission.id,
                    request.user,
                    _session_key(request),
                    request.POST,
                )
            else:
                complete_submission(
                    submission.id,
                    request.user,
                    _session_key(request),
                    request.POST,
                )
        except ResponseValidationError as error:
            errors = error.errors
        except DuplicateSubmission as error:
            return redirect('response_complete', submission_id=error.submission.id)
        else:
            if request.POST.get('action') == 'save':
                messages.success(request, 'Progress saved. You can return from this browser later.')
                return redirect('response_form', submission_id=submission.id)
            return redirect('response_complete', submission_id=submission.id)
    form_data = request.POST if request.method == 'POST' else _saved_answer_data(submission)
    return render(
        request,
        'responses/submission_form.html',
        {
            'submission': submission,
            'survey': submission.survey,
            'presented_sections': _presented_sections(
                submission,
                form_data,
                errors,
            ),
            'answer_errors': errors,
        },
        status=422 if errors else 200,
    )


def submission_complete(request, submission_id):
    submission = _accessible_submission(request, submission_id)
    if submission.status != Submission.Status.COMPLETED:
        return redirect('response_form', submission_id=submission.id)
    return render(
        request,
        'responses/submission_complete.html',
        {'submission': submission, 'survey': submission.survey},
    )
