from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponseBadRequest, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from sharing.permissions import EDIT_ROLES, OWNER_ROLES, VIEW_ROLES, get_accessible_survey

from .dashboard import creator_identity, filter_submissions, format_answer, format_duration, response_metrics
from .forms import ResponseFilterForm
from .exports import filtered_export_data, iter_csv, iter_json
from .management import permanently_delete_submission, set_analytics_exclusion
from .models import Submission


@login_required
def response_list(request, survey_id):
    survey = get_accessible_survey(request.user, survey_id, VIEW_ROLES)
    queryset = survey.submissions.select_related('version').order_by('-started_at')
    filter_form = ResponseFilterForm(request.GET or None, survey=survey)
    if filter_form.is_valid():
        filters = filter_form.cleaned_data
    else:
        filters = {
            'exclusion': 'included',
            'columns': [choice[0] for choice in ResponseFilterForm.COLUMN_CHOICES],
        }
    queryset = filter_submissions(queryset, filters, survey)
    metrics = response_metrics(queryset)
    page = Paginator(queryset, 25).get_page(request.GET.get('page'))
    for submission in page.object_list:
        submission.creator_identity = creator_identity(submission)
        submission.duration_display = format_duration(submission)
    query_parameters = request.GET.copy()
    query_parameters.pop('page', None)
    return render(
        request,
        'responses/creator_response_list.html',
        {
            'survey': survey,
            'metrics': metrics,
            'page_obj': page,
            'filter_form': filter_form,
            'selected_columns': filters['columns'],
            'query_parameters': query_parameters.urlencode(),
        },
    )


@login_required
def response_detail(request, survey_id, submission_id):
    survey = get_accessible_survey(request.user, survey_id, VIEW_ROLES)
    submission = get_object_or_404(
        Submission.objects.select_related('version', 'survey').prefetch_related(
            'answers__question__section',
        ),
        id=submission_id,
        survey=survey,
        status=Submission.Status.COMPLETED,
    )
    sections = []
    answers_by_section = {}
    for answer in submission.answers.all():
        section = answer.question.section
        answers_by_section.setdefault(section.id, {'section': section, 'answers': []})[
            'answers'
        ].append({'question': answer.question, 'value': format_answer(answer)})
    for section in submission.version.sections.order_by('order'):
        if section.id in answers_by_section:
            sections.append(answers_by_section[section.id])
    return render(
        request,
        'responses/creator_response_detail.html',
        {
            'survey': survey,
            'submission': submission,
            'creator_identity': creator_identity(submission),
            'duration_display': format_duration(submission),
            'sections': sections,
        },
    )


@require_POST
@login_required
def response_exclusion(request, survey_id, submission_id):
    get_accessible_survey(request.user, survey_id, EDIT_ROLES)
    get_object_or_404(Submission, id=submission_id, survey_id=survey_id)
    action = request.POST.get('action')
    if action not in {'exclude', 'include'}:
        messages.error(request, 'Select a valid analytics action.')
        return redirect('creator_response_detail', survey_id=survey_id, submission_id=submission_id)
    excluded = action == 'exclude'
    try:
        set_analytics_exclusion(
            submission_id,
            request.user,
            excluded=excluded,
            reason=request.POST.get('reason', ''),
        )
    except (Submission.DoesNotExist, ValidationError) as error:
        messages.error(request, '; '.join(error.messages) if isinstance(error, ValidationError) else 'Only completed responses can be changed.')
    else:
        messages.success(
            request,
            'Response excluded from analytics.' if excluded else 'Response included in analytics.',
        )
    return redirect('creator_response_detail', survey_id=survey_id, submission_id=submission_id)


@login_required
def response_delete(request, survey_id, submission_id):
    survey = get_accessible_survey(request.user, survey_id, OWNER_ROLES)
    submission = get_object_or_404(
        Submission,
        id=submission_id,
        survey=survey,
        status=Submission.Status.COMPLETED,
    )
    if request.method == 'POST':
        if request.POST.get('confirmation') != 'DELETE':
            messages.error(request, 'Type DELETE exactly to confirm permanent deletion.')
        else:
            permanently_delete_submission(submission.id, request.user)
            messages.success(request, 'Response permanently deleted. The audit record was retained.')
            return redirect('creator_response_list', survey_id=survey.id)
    return render(
        request,
        'responses/creator_response_delete.html',
        {'survey': survey, 'submission': submission},
    )


def _export_data(request, survey):
    form, submissions, questions = filtered_export_data(request.GET, survey)
    if not form.is_valid():
        return None, None, HttpResponseBadRequest('One or more export filters are invalid.')
    return submissions, questions, None


@login_required
def response_export_csv(request, survey_id):
    survey = get_accessible_survey(request.user, survey_id, VIEW_ROLES)
    submissions, questions, error = _export_data(request, survey)
    if error:
        return error
    response = StreamingHttpResponse(
        iter_csv(submissions, questions),
        content_type='text/csv; charset=utf-8',
    )
    response['Content-Disposition'] = f'attachment; filename="{survey.slug}-responses.csv"'
    return response


@login_required
def response_export_json(request, survey_id):
    survey = get_accessible_survey(request.user, survey_id, VIEW_ROLES)
    submissions, _, error = _export_data(request, survey)
    if error:
        return error
    response = StreamingHttpResponse(
        iter_json(survey, submissions),
        content_type='application/json; charset=utf-8',
    )
    response['Content-Disposition'] = f'attachment; filename="{survey.slug}-responses.json"'
    return response
