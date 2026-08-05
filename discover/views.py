"""The public survey catalogue.

Discover composes three apps into one page, which is why it lives outside surveys: the catalogue
itself, the respondent's resumable submissions, and the points a completion is worth.
"""
from django.shortcuts import render

from responses.services import resumable_submissions
from rewards.policy import BASE_COMPLETION_POINTS
from surveys.models import Survey, Topic
from surveys.presentation import presented_question_ids

from .selectors import discover_surveys


def discover(request):
    topics = [slug.strip() for slug in request.GET.getlist('topic') if slug.strip()]
    try:
        duration = int(request.GET.get('duration', ''))
    except (TypeError, ValueError):
        duration = None
    if duration not in {5, 10, 20}:
        duration = None
    try:
        minimum_points = int(request.GET.get('points', ''))
    except (TypeError, ValueError):
        minimum_points = None
    if minimum_points != BASE_COMPLETION_POINTS:
        minimum_points = None
    privacy = request.GET.get('privacy', '').strip()
    if not request.user.is_authenticated:
        privacy = Survey.IdentityMode.ANONYMOUS
    elif privacy not in Survey.IdentityMode.values:
        privacy = ''
    show_completed = request.GET.get('show_completed') == '1'
    discovery_surveys = discover_surveys(
        request.user,
        topics=topics or None,
        duration=duration,
        identity_mode=privacy or None,
        include_completed=show_completed,
    )
    if minimum_points and BASE_COMPLETION_POINTS < minimum_points:
        discovery_surveys = []
    ongoing_submissions = list(
        resumable_submissions(
            request.user,
            request.session.session_key,
        )
    )
    ongoing_survey_ids = {
        submission.survey_id
        for submission in ongoing_submissions
    }
    discovery_surveys = [
        survey
        for survey in discovery_surveys
        if survey.id not in ongoing_survey_ids
    ]
    completed_surveys = [survey for survey in discovery_surveys if survey.is_completed]
    discovery_surveys = [survey for survey in discovery_surveys if not survey.is_completed]
    for submission in ongoing_submissions:
        submission.question_count = len(
            presented_question_ids(submission.presentation)
        )
        submission.progress_percent = (
            round(
                submission.saved_answer_count
                / submission.question_count
                * 100
            )
            if submission.question_count
            else 0
        )
    template_name = (
        'discover/partials/results.html'
        if request.headers.get('x-requested-with') == 'XMLHttpRequest'
        else 'discover/discover.html'
    )
    return render(
        request,
        template_name,
        {
            'discovery_surveys': discovery_surveys,
            'completed_surveys': completed_surveys,
            'ongoing_submissions': ongoing_submissions,
            'topics': Topic.objects.filter(is_active=True),
            'selected_topics': topics,
            'selected_duration': duration,
            'selected_points': minimum_points,
            'selected_privacy': privacy,
            'show_completed': show_completed,
            'base_completion_points': BASE_COMPLETION_POINTS,
        },
    )
