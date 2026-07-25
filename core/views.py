from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render

from responses.models import Submission
from responses.services import resumable_submissions
from rewards.models import PointTransaction
from rewards.claims import BASE_COMPLETION_POINTS
from surveys.discovery import discover_surveys
from surveys.models import Survey, Topic
from surveys.presentation import presented_question_ids


COMPLETED_RESPONSES_PER_PAGE = 20


def home(request):
    return render(request, 'core/home.html')


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
        'core/partials/discovery_results.html'
        if request.headers.get('x-requested-with') == 'XMLHttpRequest'
        else 'core/discover.html'
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


@login_required
def my_responses(request):
    """Respondent-side home: what this user has answered and earned.

    Surveys the user *owns* belong to My surveys; nothing creator-facing is
    repeated here.
    """
    user = request.user
    sort = 'oldest' if request.GET.get('sort') == 'oldest' else 'newest'

    completed = (
        Submission.objects.filter(
            respondent=user,
            status=Submission.Status.COMPLETED,
        )
        .select_related('survey', 'version', 'point_transaction')
        .prefetch_related('survey__topics')
        .order_by('completed_at' if sort == 'oldest' else '-completed_at')
    )
    page = Paginator(completed, COMPLETED_RESPONSES_PER_PAGE).get_page(
        request.GET.get('page')
    )
    for submission in page:
        # Reverse one-to-one: absent whenever the completion earned no points
        # (self-owned survey, collaborator, or an already rewarded survey).
        transaction_record = getattr(submission, 'point_transaction', None)
        submission.points_earned = transaction_record.amount if transaction_record else 0

    ongoing_submissions = list(
        resumable_submissions(user, request.session.session_key)
    )
    for submission in ongoing_submissions:
        submission.question_count = len(
            presented_question_ids(submission.presentation)
        )
        submission.progress_percent = (
            round(submission.saved_answer_count / submission.question_count * 100)
            if submission.question_count
            else 0
        )

    return render(
        request,
        'core/my_responses.html',
        {
            'profile': user.profile,
            'points_balance': PointTransaction.objects.balance_for(user),
            'surveys_completed_count': page.paginator.count,
            'completed_page': page,
            'ongoing_submissions': ongoing_submissions,
            'sort': sort,
        },
    )
