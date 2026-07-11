from collections import Counter
from statistics import median
from uuid import UUID

from django.db.models import Exists, OuterRef, Q, TextField
from django.db.models.functions import Cast

from .models import Answer, Submission


def response_metrics(submissions):
    starts = submissions.count()
    completed_queryset = submissions.filter(status=Submission.Status.COMPLETED)
    completions = completed_queryset.count()
    completed_timestamps = list(
        completed_queryset.values_list('started_at', 'completed_at')
    )
    durations = [
        (completed_at - started_at).total_seconds()
        for started_at, completed_at in completed_timestamps
        if completed_at
    ]
    trend = Counter(
        completed_at.date()
        for _, completed_at in completed_timestamps
        if completed_at
    )
    return {
        'starts': starts,
        'completions': completions,
        'completion_rate': round(completions / starts * 100, 1) if starts else 0,
        'median_duration_seconds': round(median(durations)) if durations else None,
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
    return queryset


def creator_identity(submission):
    if (
        submission.status == Submission.Status.COMPLETED
        and submission.survey.identity_mode == submission.survey.IdentityMode.IDENTIFIED
    ):
        return submission.identity_data
    return None


def format_duration(submission):
    if not submission.completed_at:
        return '—'
    seconds = max(0, round((submission.completed_at - submission.started_at).total_seconds()))
    minutes, seconds = divmod(seconds, 60)
    return f'{minutes}m {seconds}s' if minutes else f'{seconds}s'


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
