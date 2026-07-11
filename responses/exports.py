import csv
import json

from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone

from surveys.models import Question, SurveyVersion

from .dashboard import creator_identity, filter_submissions
from .forms import ResponseFilterForm


FIXED_COLUMNS = (
    'response_id',
    'version',
    'started_at',
    'completed_at',
    'status',
    'source',
    'is_eligible',
    'is_excluded',
    'duration_seconds',
    'identity_name',
    'identity_email',
)


class Echo:
    def write(self, value):
        return value


def filtered_export_data(query_parameters, survey):
    form = ResponseFilterForm(query_parameters, survey=survey)
    if not form.is_valid():
        return form, None, None
    submissions = filter_submissions(
        survey.submissions.select_related('version').prefetch_related(
            'answers__question__section',
        ),
        form.cleaned_data,
        survey,
    ).order_by('-started_at')
    questions = Question.objects.filter(
        section__version__survey=survey,
        section__version__status__in=(
            SurveyVersion.Status.PUBLISHED,
            SurveyVersion.Status.RETIRED,
        ),
    ).select_related('section__version')
    if form.cleaned_data.get('version'):
        questions = questions.filter(section__version_id=form.cleaned_data['version'])
    return form, submissions, list(
        questions.order_by('section__version__number', 'section__order', 'order')
    )


def _serialized_value(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, cls=DjangoJSONEncoder)
    return value


def _csv_safe(value):
    if isinstance(value, str) and value.startswith(('=', '+', '-', '@', '\t', '\r')):
        return f"'{value}"
    return value


def response_record(submission):
    identity = creator_identity(submission) or {}
    duration = None
    if submission.completed_at:
        duration = max(
            0,
            round((submission.completed_at - submission.started_at).total_seconds()),
        )
    return {
        'response_id': str(submission.id),
        'version': submission.version.number,
        'started_at': submission.started_at.isoformat(),
        'completed_at': submission.completed_at.isoformat() if submission.completed_at else None,
        'status': submission.status,
        'source': submission.source,
        'is_eligible': submission.is_eligible,
        'is_excluded': submission.is_excluded,
        'duration_seconds': duration,
        'identity_name': identity.get('name'),
        'identity_email': identity.get('email'),
        'answers': [
            {
                'question_id': str(answer.question_id),
                'version': answer.question.section.version.number,
                'section': answer.question.section.title,
                'prompt': answer.question.prompt,
                'type': answer.question.type,
                'value': answer.value,
            }
            for answer in submission.answers.all()
        ],
    }


def question_column(question):
    return f'v{question.section.version.number} · {question.prompt} [{question.id}]'


def iter_csv(submissions, questions):
    writer = csv.writer(Echo())
    yield '\ufeff' + writer.writerow(
        (*FIXED_COLUMNS, *(_csv_safe(question_column(question)) for question in questions))
    )
    question_ids = [str(question.id) for question in questions]
    for submission in submissions.iterator(chunk_size=500):
        record = response_record(submission)
        answer_values = {
            answer['question_id']: _serialized_value(answer['value'])
            for answer in record.pop('answers')
        }
        yield writer.writerow(
            [_csv_safe(record[column]) for column in FIXED_COLUMNS]
            + [_csv_safe(answer_values.get(question_id, '')) for question_id in question_ids]
        )


def iter_json(survey, submissions):
    encoder = DjangoJSONEncoder(ensure_ascii=False, separators=(',', ':'))
    yield '{"survey":'
    yield encoder.encode({'id': str(survey.id), 'title': survey.title})
    yield ',"generated_at":'
    yield encoder.encode(timezone.now().isoformat())
    yield ',"responses":['
    first = True
    for submission in submissions.iterator(chunk_size=500):
        if not first:
            yield ','
        yield encoder.encode(response_record(submission))
        first = False
    yield ']}'
