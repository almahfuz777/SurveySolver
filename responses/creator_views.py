from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render

from surveys.models import Survey

from .dashboard import creator_identity, format_answer, format_duration, response_metrics
from .models import Submission


def _owned_survey(user, survey_id):
    return get_object_or_404(Survey, id=survey_id, owner=user)


@login_required
def response_list(request, survey_id):
    survey = _owned_survey(request.user, survey_id)
    queryset = survey.submissions.select_related('version').order_by('-started_at')
    metrics = response_metrics(queryset)
    page = Paginator(queryset, 25).get_page(request.GET.get('page'))
    for submission in page.object_list:
        submission.creator_identity = creator_identity(submission)
        submission.duration_display = format_duration(submission)
    return render(
        request,
        'responses/creator_response_list.html',
        {'survey': survey, 'metrics': metrics, 'page_obj': page},
    )


@login_required
def response_detail(request, survey_id, submission_id):
    survey = _owned_survey(request.user, survey_id)
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
