import csv
from tempfile import SpooledTemporaryFile

from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font, PatternFill

from surveys.models import Question, SurveyVersion

from .dashboard import filter_response_sheet, format_answer_cell
from .forms import ResponseSheetFilterForm
from .models import Submission


TIMESTAMP_COLUMN = 'Submitted at'


class Echo:
    def write(self, value):
        return value


def filtered_export_data(query_parameters, survey):
    questions = response_sheet_questions(survey)
    form = ResponseSheetFilterForm(
        query_parameters,
        questions=questions,
    )
    if not form.is_valid():
        return form, None, None
    submissions = filter_response_sheet(
        survey.submissions.filter(
            status=Submission.Status.COMPLETED,
            is_excluded=False,
        ).select_related('version').prefetch_related(
            'answers__question__section',
        ),
        form.cleaned_data,
        questions,
    )
    return form, submissions, questions


def response_sheet_questions(survey, *, version_id=None):
    questions = Question.objects.filter(
        section__version__survey=survey,
        section__version__status__in=(
            SurveyVersion.Status.PUBLISHED,
            SurveyVersion.Status.RETIRED,
        ),
    ).select_related('section__version').prefetch_related('choices')
    if version_id:
        questions = questions.filter(section__version_id=version_id)
    questions = list(
        questions.order_by('section__version__number', 'section__order', 'order')
    )
    include_version = len(
        {question.section.version_id for question in questions}
    ) > 1
    for question in questions:
        question.sheet_label = question_column(
            question,
            include_version=include_version,
        )
    return questions


def _csv_safe(value):
    if isinstance(value, str) and value.startswith(('=', '+', '-', '@', '\t', '\r')):
        return f"'{value}"
    return value


def _excel_safe(value):
    value = _csv_safe(value)
    if not isinstance(value, str):
        return value
    value = ILLEGAL_CHARACTERS_RE.sub('', value)
    if len(value) > 32767:
        value = f'{value[:32740]}… [truncated for Excel]'
    return value


def _blank_if_none(value):
    return '' if value is None else value


def response_sheet_record(submission, questions):
    answer_by_question = {
        answer.question_id: format_answer_cell(answer)
        for answer in submission.answers.all()
    }
    return {
        'submitted_at': submission.completed_at.isoformat(),
        'answers': {
            str(question.id): answer_by_question.get(question.id)
            for question in questions
        },
    }


def question_column(question, *, include_version=True):
    if include_version:
        return f'v{question.section.version.number} · {question.prompt}'
    return question.prompt


def iter_csv(submissions, questions):
    writer = csv.writer(Echo())
    yield '\ufeff' + writer.writerow(
        (TIMESTAMP_COLUMN, *(_csv_safe(question.sheet_label) for question in questions))
    )
    for submission in submissions.iterator(chunk_size=500):
        record = response_sheet_record(submission, questions)
        yield writer.writerow(
            [_csv_safe(record['submitted_at'])]
            + [
                _csv_safe(
                    _blank_if_none(record['answers'].get(str(question.id)))
                )
                for question in questions
            ]
        )


def iter_json(survey, submissions, questions):
    encoder = DjangoJSONEncoder(ensure_ascii=False, separators=(',', ':'))
    yield '{"survey":'
    yield encoder.encode({'id': str(survey.id), 'title': survey.title})
    yield ',"questions":'
    yield encoder.encode(
        [
            {'id': str(question.id), 'label': question.sheet_label}
            for question in questions
        ]
    )
    yield ',"generated_at":'
    yield encoder.encode(timezone.now().isoformat())
    yield ',"responses":['
    first = True
    for submission in submissions.iterator(chunk_size=500):
        if not first:
            yield ','
        yield encoder.encode(response_sheet_record(submission, questions))
        first = False
    yield ']}'


def build_excel(survey, submissions, questions):
    output = SpooledTemporaryFile(max_size=5 * 1024 * 1024, mode='w+b')
    workbook = Workbook(write_only=True)
    worksheet = workbook.create_sheet('Responses')
    worksheet.freeze_panes = 'A2'
    headers = (TIMESTAMP_COLUMN, *(question.sheet_label for question in questions))
    header_cells = []
    for header in headers:
        cell = WriteOnlyCell(worksheet, value=_excel_safe(header))
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='312E81')
        header_cells.append(cell)
    worksheet.append(header_cells)
    for submission in submissions.iterator(chunk_size=500):
        record = response_sheet_record(submission, questions)
        worksheet.append(
            [_excel_safe(record['submitted_at'])]
            + [
                _excel_safe(
                    _blank_if_none(record['answers'].get(str(question.id)))
                )
                for question in questions
            ]
        )
    metadata = workbook.create_sheet('About')
    metadata.append(('Survey', _excel_safe(survey.title)))
    metadata.append(('Survey ID', str(survey.id)))
    metadata.append(('Generated at', timezone.now().isoformat()))
    workbook.save(output)
    output.seek(0)
    return output
