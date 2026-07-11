from collections import Counter
from statistics import median

from accounts.models import Profile
from django_countries import countries

from responses.models import Answer, Submission


PRIVACY_THRESHOLD = 5


def overview_metrics(submissions):
    starts = submissions.count()
    completed = list(
        submissions.filter(status=Submission.Status.COMPLETED).values_list(
            'started_at',
            'completed_at',
        )
    )
    completions = len(completed)
    durations = [
        (completed_at - started_at).total_seconds()
        for started_at, completed_at in completed
        if completed_at
    ]
    starts_by_day = Counter(started.date() for started in submissions.values_list('started_at', flat=True))
    completions_by_day = Counter(
        completed_at.date() for _, completed_at in completed if completed_at
    )
    trend_dates = sorted(set(starts_by_day) | set(completions_by_day))
    return {
        'starts': starts,
        'completions': completions,
        'abandonments': starts - completions,
        'completion_rate': round(completions / starts * 100, 1) if starts else 0,
        'median_duration_seconds': round(median(durations)) if durations else None,
        'trend': [
            {
                'date': date,
                'starts': starts_by_day[date],
                'completions': completions_by_day[date],
            }
            for date in trend_dates
        ],
    }


def _answer_labels(answer):
    value = answer.value
    question_type = answer.question.type
    if question_type in {
        answer.question.Type.SINGLE_CHOICE,
        answer.question.Type.DROPDOWN,
    }:
        return [value['label']]
    if question_type == answer.question.Type.MULTIPLE_CHOICE:
        return [choice['label'] for choice in value]
    if question_type == answer.question.Type.RANKING:
        return [value[0]['label']] if value else []
    if question_type == answer.question.Type.SCALE:
        return [str(value)]
    if question_type == answer.question.Type.LIKERT_MATRIX:
        return [
            f"{row['row_label']} — {row['choice_label']}"
            for row in value.values()
        ]
    return []


def question_summaries(submissions):
    answers = Answer.objects.filter(
        submission__in=submissions.filter(status=Submission.Status.COMPLETED),
    ).select_related('question__section__version')
    summaries = {}
    for answer in answers:
        question = answer.question
        summary = summaries.setdefault(
            question.id,
            {
                'question': question,
                'version_number': question.section.version.number,
                'answered': 0,
                'distribution': Counter(),
            },
        )
        summary['answered'] += 1
        summary['distribution'].update(_answer_labels(answer))
    results = []
    for summary in summaries.values():
        distribution = summary.pop('distribution')
        summary['distribution'] = [
            {'label': label, 'count': count}
            for label, count in distribution.most_common()
        ]
        summary['max_count'] = max(distribution.values(), default=0)
        results.append(summary)
    return sorted(results, key=lambda item: (item['version_number'], item['question'].order))


def demographic_summaries(submissions):
    value_labels = {
        'education_level': dict(Profile.EducationLevel.choices),
        'country': dict(countries),
        'gender': dict(Profile.Gender.choices),
        'employment_status': dict(Profile.EmploymentStatus.choices),
    }
    field_labels = {
        'education_level': 'Education',
        'country': 'Country',
        'gender': 'Gender',
        'employment_status': 'Employment',
    }
    values = list(
        submissions.filter(status=Submission.Status.COMPLETED).values_list(
            'eligibility_data',
            flat=True,
        )
    )
    summaries = []
    for field, labels in value_labels.items():
        counts = Counter(snapshot.get(field) for snapshot in values if snapshot.get(field))
        if not counts:
            continue
        visible = [
            {'label': labels.get(value, value), 'count': count}
            for value, count in counts.most_common()
            if count >= PRIVACY_THRESHOLD
        ]
        summaries.append(
            {
                'label': field_labels[field],
                'groups': visible,
                'has_suppressed_groups': any(
                    count < PRIVACY_THRESHOLD for count in counts.values()
                ),
                'max_count': max((group['count'] for group in visible), default=0),
            }
        )
    return summaries


def survey_analytics(survey, version=None):
    submissions = survey.submissions.filter(is_excluded=False)
    if version:
        submissions = submissions.filter(version=version)
    return {
        'metrics': overview_metrics(submissions),
        'questions': question_summaries(submissions),
        'demographics': demographic_summaries(submissions),
    }
