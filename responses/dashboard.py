from collections import Counter
from statistics import median
from uuid import UUID

from django.db.models import (
    Exists,
    F,
    FloatField,
    OuterRef,
    Q,
    Subquery,
    TextField,
)
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast

from surveys.models import Question

from .durations import duration_seconds, format_duration_seconds
from .models import Answer, Submission


def response_metrics(submissions):
    starts = submissions.count()
    completed_queryset = submissions.filter(status=Submission.Status.COMPLETED)
    completions = completed_queryset.count()
    completed_timestamps = list(
        completed_queryset.values_list('started_at', 'completed_at')
    )
    durations = [
        duration
        for started_at, completed_at in completed_timestamps
        if (duration := duration_seconds(started_at, completed_at)) is not None
    ]
    trend = Counter(
        completed_at.date()
        for _, completed_at in completed_timestamps
        if completed_at
    )
    median_duration_seconds = round(median(durations)) if durations else None
    return {
        'starts': starts,
        'completions': completions,
        'completion_rate': round(completions / starts * 100, 1) if starts else 0,
        'median_duration_seconds': median_duration_seconds,
        'median_duration_display': format_duration_seconds(median_duration_seconds),
        'completion_trend': sorted(trend.items()),
    }


def filter_submissions(queryset, filters, survey):
    version = filters.get('version')
    if version:
        queryset = queryset.filter(version_id=version)
    if filters.get('date_from'):
        queryset = queryset.filter(started_at__date__gte=filters['date_from'])
    if filters.get('date_to'):
        queryset = queryset.filter(started_at__date__lte=filters['date_to'])
    completion = filters.get('completion')
    if completion in Submission.Status.values:
        queryset = queryset.filter(status=completion)
    if filters.get('source'):
        queryset = queryset.filter(source=filters['source'])
    eligibility = filters.get('eligibility')
    if eligibility == 'eligible':
        queryset = queryset.filter(is_eligible=True)
    elif eligibility == 'ineligible':
        queryset = queryset.filter(is_eligible=False)
    exclusion = filters.get('exclusion') or 'included'
    if exclusion == 'included':
        queryset = queryset.filter(is_excluded=False)
    elif exclusion == 'excluded':
        queryset = queryset.filter(is_excluded=True)
    search = filters.get('search', '').strip()
    if search:
        answer_matches = (
            Answer.objects.filter(submission_id=OuterRef('pk'))
            .annotate(search_text=Cast('value', TextField()))
            .filter(search_text__icontains=search)
        )
        queryset = queryset.annotate(has_matching_answer=Exists(answer_matches))
        search_query = Q(has_matching_answer=True)
        if survey.identity_mode == survey.IdentityMode.IDENTIFIED:
            queryset = queryset.annotate(identity_text=Cast('identity_data', TextField()))
            search_query |= Q(identity_text__icontains=search)
        try:
            search_query |= Q(id=UUID(search))
        except ValueError:
            pass
        queryset = queryset.filter(search_query)
    ordering = 'started_at' if filters.get('sort') == 'oldest' else '-started_at'
    return queryset.order_by(ordering)


def filter_response_sheet(queryset, filters, questions):
    if filters.get('submitted_from'):
        queryset = queryset.filter(
            completed_at__date__gte=filters['submitted_from'],
        )
    if filters.get('submitted_to'):
        queryset = queryset.filter(
            completed_at__date__lte=filters['submitted_to'],
        )

    questions_by_id = {str(question.id): question for question in questions}
    for question_id, question in questions_by_id.items():
        value = filters.get(f'answer_{question_id}', '').strip()
        if not value:
            continue
        matching_answers = Answer.objects.filter(
            submission_id=OuterRef('pk'),
            question_id=question.id,
        )
        if question.type in {
            Question.Type.SINGLE_CHOICE,
            Question.Type.DROPDOWN,
        }:
            matching_answers = matching_answers.filter(
                value__label__iexact=value,
            )
        elif question.type in {
            Question.Type.SCALE,
            Question.Type.NUMBER,
        }:
            try:
                numeric_value = float(value)
            except ValueError:
                matching_answers = matching_answers.none()
            else:
                matching_answers = matching_answers.filter(value=numeric_value)
        else:
            matching_answers = (
                matching_answers.annotate(answer_text=Cast('value', TextField()))
                .filter(answer_text__icontains=value)
            )
        queryset = queryset.annotate(
            **{f'matches_{question.id.hex}': Exists(matching_answers)}
        ).filter(**{f'matches_{question.id.hex}': True})

    sort_key = filters.get('sheet_sort') or 'timestamp'
    direction = filters.get('sheet_direction') or 'desc'
    descending = direction == 'desc'
    if sort_key == 'timestamp':
        ordering = F('completed_at')
    else:
        question = questions_by_id.get(sort_key)
        if question is None:
            ordering = F('completed_at')
            descending = True
        else:
            answer_sort = Answer.objects.filter(
                submission_id=OuterRef('pk'),
                question_id=question.id,
            )
            if question.type in {
                Question.Type.SINGLE_CHOICE,
                Question.Type.DROPDOWN,
            }:
                output_field = TextField()
                answer_sort = answer_sort.annotate(
                    sort_value=KeyTextTransform('label', 'value'),
                )
            elif question.type in {
                Question.Type.SCALE,
                Question.Type.NUMBER,
            }:
                output_field = FloatField()
                answer_sort = answer_sort.annotate(
                    sort_value=Cast('value', FloatField()),
                )
            elif question.type in {
                Question.Type.MULTIPLE_CHOICE,
                Question.Type.RANKING,
            }:
                output_field = TextField()
                answer_sort = answer_sort.annotate(
                    sort_value=KeyTextTransform(
                        'label',
                        KeyTextTransform('0', 'value'),
                    ),
                )
            else:
                output_field = TextField()
                answer_sort = answer_sort.annotate(
                    sort_value=Cast('value', TextField()),
                )
            queryset = queryset.annotate(
                sheet_sort_value=Subquery(
                    answer_sort.values('sort_value')[:1],
                    output_field=output_field,
                ),
            )
            ordering = F('sheet_sort_value')

    ordering = (
        ordering.desc(nulls_last=True)
        if descending
        else ordering.asc(nulls_last=True)
    )
    return queryset.order_by(ordering, '-completed_at', 'id')


def creator_identity(submission):
    if (
        submission.status == Submission.Status.COMPLETED
        and submission.survey.identity_mode == submission.survey.IdentityMode.IDENTIFIED
    ):
        return submission.identity_data
    return None


def format_duration(submission):
    seconds = duration_seconds(submission.started_at, submission.completed_at)
    return format_duration_seconds(seconds) or '—'


def format_answer(answer):
    value = answer.value
    question_type = answer.question.type
    if question_type in {
        answer.question.Type.SINGLE_CHOICE,
        answer.question.Type.DROPDOWN,
    }:
        return value['label']
    if question_type == answer.question.Type.MULTIPLE_CHOICE:
        return ', '.join(choice['label'] for choice in value)
    if question_type == answer.question.Type.RANKING:
        return [choice['label'] for choice in value]
    if question_type == answer.question.Type.LIKERT_MATRIX:
        return [
            (row_value['row_label'], row_value['choice_label'])
            for row_value in value.values()
        ]
    return value


def format_answer_cell(answer):
    value = format_answer(answer)
    if isinstance(value, list):
        if value and isinstance(value[0], tuple):
            return '; '.join(f'{row}: {choice}' for row, choice in value)
        return ', '.join(str(item) for item in value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return value
