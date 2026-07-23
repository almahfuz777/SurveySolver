from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import FileResponse, HttpResponseBadRequest, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from sharing.permissions import EDIT_ROLES, OWNER_ROLES, VIEW_ROLES, get_accessible_survey

from .dashboard import (
    creator_identity,
    filter_submissions,
    filter_response_sheet,
    format_answer,
    format_answer_cell,
    format_duration,
    response_metrics,
)
from .exports import (
    build_excel,
    filtered_export_data,
    iter_csv,
    iter_json,
    response_sheet_questions,
)
from .forms import ResponseFilterForm, ResponseSheetFilterForm
from .management import permanently_delete_submission, set_analytics_exclusion
from .models import Submission


@login_required
def response_list(request, survey_id):
    survey = get_accessible_survey(request.user, survey_id, VIEW_ROLES)
    base_queryset = survey.submissions.select_related('version').prefetch_related(
        'answers__question',
    )
    metrics = response_metrics(base_queryset.filter(is_excluded=False))

    activity_data = request.GET.copy()
    for parameter in list(activity_data):
        if not parameter.startswith('activity-'):
            activity_data.pop(parameter, None)
    filter_form = ResponseFilterForm(
        activity_data or None,
        survey=survey,
        prefix='activity',
    )
    if filter_form.is_valid():
        activity_filters = filter_form.cleaned_data
    else:
        activity_filters = {
            'exclusion': 'included',
            'sort': 'newest',
            'columns': [choice[0] for choice in ResponseFilterForm.COLUMN_CHOICES],
        }
    activity_queryset = filter_submissions(
        base_queryset,
        activity_filters,
        survey,
    )
    page = Paginator(activity_queryset, 25).get_page(request.GET.get('page'))

    sheet_questions = response_sheet_questions(survey)
    sheet_data = request.GET.copy()
    for parameter in list(sheet_data):
        if not (
            parameter.startswith('answer_')
            or parameter.startswith('sheet_')
            or parameter in {'submitted_from', 'submitted_to'}
        ):
            sheet_data.pop(parameter, None)
    sheet_filter_form = ResponseSheetFilterForm(
        sheet_data or None,
        questions=sheet_questions,
    )
    if sheet_filter_form.is_valid():
        sheet_filters = sheet_filter_form.cleaned_data
    else:
        sheet_filters = {
            'sheet_sort': 'timestamp',
            'sheet_direction': 'desc',
        }
    sheet_queryset = filter_response_sheet(
        base_queryset.filter(
            status=Submission.Status.COMPLETED,
            is_excluded=False,
        ),
        sheet_filters,
        sheet_questions,
    )
    responses_page = Paginator(
        sheet_queryset,
        25,
    ).get_page(request.GET.get('response_page'))

    for submission in page.object_list:
        submission.creator_identity = creator_identity(submission)
        submission.duration_display = format_duration(submission)
    for submission in responses_page.object_list:
        answer_by_question = {
            answer.question_id: answer
            for answer in submission.answers.all()
        }
        submission.sheet_cells = [
            format_answer_cell(answer_by_question[question.id])
            if question.id in answer_by_question
            else None
            for question in sheet_questions
        ]

    activity_query = request.GET.copy()
    activity_query.pop('page', None)
    activity_query.pop('dashboard_view', None)
    sheet_query = request.GET.copy()
    sheet_query.pop('response_page', None)
    sheet_query.pop('dashboard_view', None)

    activity_filter_names = {
        filter_form.add_prefix(field_name)
        for field_name in filter_form.fields
    }
    activity_reset_query = request.GET.copy()
    for field_name in activity_filter_names:
        activity_reset_query.pop(field_name, None)
    activity_reset_query.pop('page', None)
    activity_reset_query.pop('dashboard_view', None)

    sheet_field_names = set(sheet_filter_form.fields)
    sheet_reset_query = request.GET.copy()
    for field_name in sheet_field_names:
        sheet_reset_query.pop(field_name, None)
    sheet_reset_query.pop('response_page', None)
    sheet_reset_query.pop('dashboard_view', None)
    sheet_export_query = request.GET.copy()
    for field_name in list(sheet_export_query):
        if field_name not in sheet_field_names:
            sheet_export_query.pop(field_name, None)

    sheet_sort = sheet_filters.get('sheet_sort') or 'timestamp'
    sheet_direction = sheet_filters.get('sheet_direction') or 'desc'

    def sort_query(sort_key):
        query = request.GET.copy()
        query['sheet_sort'] = sort_key
        query['sheet_direction'] = (
            'desc'
            if sheet_sort == sort_key and sheet_direction == 'asc'
            else 'asc'
        )
        query.pop('response_page', None)
        query.pop('dashboard_view', None)
        return query.urlencode()

    for question in sheet_questions:
        field_name = f'answer_{question.id}'
        question.filter_name = field_name
        question.filter_value = sheet_filters.get(field_name, '')
        question.is_filtered = bool(question.filter_value)
        if question.type in {
            question.Type.SINGLE_CHOICE,
            question.Type.DROPDOWN,
            question.Type.MULTIPLE_CHOICE,
            question.Type.RANKING,
        }:
            question.filter_options = [
                choice.label
                for choice in question.choices.all()
            ]
        elif question.type == question.Type.SCALE:
            scale_min = question.config.get('scale_min', 1)
            scale_max = question.config.get(
                'scale_max',
                question.config.get('scale', 5),
            )
            question.filter_options = [
                str(value)
                for value in range(scale_min, scale_max + 1)
            ]
        else:
            question.filter_options = []
        question.is_sorted = sheet_sort == str(question.id)
        question.sort_direction = sheet_direction if question.is_sorted else ''
        question.sort_query = sort_query(str(question.id))

    sheet_filters_active = any(
        sheet_filters.get(field_name)
        for field_name in sheet_field_names
        if field_name.startswith('answer_')
    ) or bool(
        sheet_filters.get('submitted_from')
        or sheet_filters.get('submitted_to')
    )
    sheet_state_active = sheet_filters_active or (
        sheet_sort != 'timestamp' or sheet_direction != 'desc'
    )

    context = {
        'survey': survey,
        'metrics': metrics,
        'page_obj': page,
        'responses_page': responses_page,
        'filter_form': filter_form,
        'sheet_filter_form': sheet_filter_form,
        'selected_columns': activity_filters['columns'],
        'activity_query_parameters': activity_query.urlencode(),
        'sheet_query_parameters': sheet_query.urlencode(),
        'sheet_questions': sheet_questions,
        'sheet_column_count': len(sheet_questions) + 2,
        'activity_filters_active': any(
            field_name in request.GET
            for field_name in activity_filter_names
        ),
        'activity_reset_query': activity_reset_query.urlencode(),
        'sheet_reset_query': sheet_reset_query.urlencode(),
        'sheet_export_query': sheet_export_query.urlencode(),
        'sheet_filters_active': sheet_filters_active,
        'sheet_state_active': sheet_state_active,
        'sheet_sort': sheet_sort,
        'sheet_direction': sheet_direction,
        'timestamp_sort_query': sort_query('timestamp'),
        'submitted_from': sheet_filters.get('submitted_from'),
        'submitted_to': sheet_filters.get('submitted_to'),
    }
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        partial = {
            'activity': 'responses/partials/response_activity.html',
            'sheet': 'responses/partials/response_sheet.html',
        }.get(request.GET.get('dashboard_view'))
        if partial:
            return render(request, partial, context)

    return render(
        request,
        'responses/creator_response_list.html',
        context,
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
    submissions, questions, error = _export_data(request, survey)
    if error:
        return error
    response = StreamingHttpResponse(
        iter_json(survey, submissions, questions),
        content_type='application/json; charset=utf-8',
    )
    response['Content-Disposition'] = f'attachment; filename="{survey.slug}-responses.json"'
    return response


@login_required
def response_export_excel(request, survey_id):
    survey = get_accessible_survey(request.user, survey_id, VIEW_ROLES)
    submissions, questions, error = _export_data(request, survey)
    if error:
        return error
    return FileResponse(
        build_excel(survey, submissions, questions),
        as_attachment=True,
        filename=f'{survey.slug}-responses.xlsx',
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
