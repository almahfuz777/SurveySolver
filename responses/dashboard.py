from collections import Counter
from statistics import median

from .models import Submission


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
