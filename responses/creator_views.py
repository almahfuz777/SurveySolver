from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import models
from django.http import FileResponse, HttpResponseBadRequest, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from sharing.permissions import OWNER_ROLES, VIEW_ROLES, get_accessible_survey
from surveys.models import SurveyVersion

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
from .management import permanently_delete_submission
from .models import Submission


@login_required
def response_list(request, survey_id):
    survey = get_accessible_survey(request.user, survey_id, VIEW_ROLES)
    versions = list(
        survey.versions.exclude(status=SurveyVersion.Status.DRAFT)
        .annotate(
            completed_count=models.Count(
                'submissions',
                filter=models.Q(submissions__status=Submission.Status.COMPLETED),
            ),
            start_count=models.Count('submissions'),
        )
        .order_by('-number')
    )
    active_version = next(
        (version for version in versions if version.status == SurveyVersion.Status.PUBLISHED),
        None,
    )
    selected_version_id = request.GET.get('sheet_version')
    selected_version = next(
        (version for version in versions if str(version.id) == selected_version_id),
        None,
    )
    if selected_version is None:
        selected_version = active_version or (versions[0] if versions else None)
    base_queryset = survey.submissions.select_related('version').prefetch_related(
        'answers__question',
    )
    selected_queryset = (
        base_queryset.filter(version=selected_version)
        if selected_version is not None
        else base_queryset.none()
    )
    metrics = response_metrics(selected_queryset)

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
            'sort': 'newest',
            'columns': [choice[0] for choice in ResponseFilterForm.COLUMN_CHOICES],
        }
    activity_queryset = filter_submissions(
        base_queryset,
        activity_filters,
        survey,
    )
    page = Paginator(activity_queryset, 25).get_page(request.GET.get('page'))

    sheet_questions = response_sheet_questions(
        survey,
        version_id=selected_version.id if selected_version else None,
    )
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
        selected_queryset.filter(
            status=Submission.Status.COMPLETED,
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
        if field_name not in sheet_field_names and field_name != 'sheet_version':
            sheet_export_query.pop(field_name, None)
    if selected_version:
        sheet_export_query['sheet_version'] = str(selected_version.id)

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
        'versions': versions,
        'selected_version': selected_version,
        'active_version': active_version,
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
            'sheet': 'responses/partials/response_sheet_versions.html',
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
    section_map = {
        str(section.id): section
        for section in submission.version.sections.all()
    }
    answers = {
        str(answer.question_id): answer
        for answer in submission.answers.all()
    }
    sections = []
    for section_data in submission.presentation.get('sections', []):
        section_answers = []
        for question_data in section_data.get('questions', []):
            answer = answers.get(question_data['id'])
            if answer is not None:
                section_answers.append(
                    {
                        'question': answer.question,
                        'value': format_answer(answer),
                    }
                )
        section = section_map.get(section_data['id'])
        if section is not None and section_answers:
            sections.append({'section': section, 'answers': section_answers})
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


@login_required
@require_POST
def response_delete(request, survey_id, submission_id):
    survey = get_accessible_survey(request.user, survey_id, OWNER_ROLES)
    submission = get_object_or_404(
        Submission,
        id=submission_id,
        survey=survey,
        status=Submission.Status.COMPLETED,
    )
    permanently_delete_submission(submission.id, request.user)
    messages.success(request, 'Response permanently deleted.')
    return redirect('creator_response_list', survey_id=survey.id)


def _export_data(request, survey):
    form, submissions, questions, version = filtered_export_data(request.GET, survey)
    if not form.is_valid():
        return None, None, None, HttpResponseBadRequest('One or more export filters are invalid.')
    return submissions, questions, version, None


def _export_basename(survey, version):
    # Carry the exact version number and its publication-time title snapshot in
    # the filename so downloads from different versions stay distinct and
    # self-identifying; the CSV table itself stays metadata-free.
    if version is not None:
        title = slugify(version.title_snapshot or survey.title) or 'survey'
        return f'{title}-v{version.number}-responses'
    return f'{survey.slug}-responses'


@login_required
def response_export_csv(request, survey_id):
    survey = get_accessible_survey(request.user, survey_id, VIEW_ROLES)
    submissions, questions, version, error = _export_data(request, survey)
    if error:
        return error
    response = StreamingHttpResponse(
        iter_csv(submissions, questions),
        content_type='text/csv; charset=utf-8',
    )
    response['Content-Disposition'] = (
        f'attachment; filename="{_export_basename(survey, version)}.csv"'
    )
    return response


@login_required
def response_export_json(request, survey_id):
    survey = get_accessible_survey(request.user, survey_id, VIEW_ROLES)
    submissions, questions, version, error = _export_data(request, survey)
    if error:
        return error
    response = StreamingHttpResponse(
        iter_json(survey, submissions, questions, version),
        content_type='application/json; charset=utf-8',
    )
    response['Content-Disposition'] = (
        f'attachment; filename="{_export_basename(survey, version)}.json"'
    )
    return response


@login_required
def response_export_excel(request, survey_id):
    survey = get_accessible_survey(request.user, survey_id, VIEW_ROLES)
    submissions, questions, version, error = _export_data(request, survey)
    if error:
        return error
    return FileResponse(
        build_excel(survey, submissions, questions, version),
        as_attachment=True,
        filename=f'{_export_basename(survey, version)}.xlsx',
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
