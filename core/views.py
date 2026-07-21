from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import render

from responses.models import Submission
from rewards.models import BadgeAward, PointTransaction
from rewards.claims import BASE_COMPLETION_POINTS
from surveys.discovery import discover_surveys
from surveys.models import Survey, Topic
from surveys.services import discard_empty_drafts


def home(request):
    return render(request, 'core/home.html')


def discover(request):
    topic = request.GET.get('topic', '').strip()
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
    discovery_surveys = discover_surveys(
        request.user,
        topic=topic or None,
        duration=duration,
        identity_mode=privacy or None,
    )
    if minimum_points and BASE_COMPLETION_POINTS < minimum_points:
        discovery_surveys = []
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
            'topics': Topic.objects.filter(is_active=True),
            'selected_topic': topic,
            'selected_duration': duration,
            'selected_points': minimum_points,
            'selected_privacy': privacy,
            'base_completion_points': BASE_COMPLETION_POINTS,
        },
    )


@login_required
def overview(request):
    user = request.user
    discard_empty_drafts(user)
    owned_surveys = Survey.objects.owned_by(user).filter(deleted_at__isnull=True)

    # Per-status breakdown of the user's own (non-deleted) surveys.
    status_rows = owned_surveys.values('status').annotate(count=Count('id'))
    counts_by_status = {row['status']: row['count'] for row in status_rows}
    survey_status_counts = {
        'draft': counts_by_status.get(Survey.Status.DRAFT, 0),
        'published': counts_by_status.get(Survey.Status.PUBLISHED, 0),
        'closed': counts_by_status.get(Survey.Status.CLOSED, 0),
    }
    active_survey_count = sum(survey_status_counts.values())

    # Responses this user has *received* on surveys they own.
    total_responses = Submission.objects.filter(
        survey__owner=user,
        status=Submission.Status.COMPLETED,
    ).count()

    # Respondent side: surveys this user has *completed* for points.
    surveys_completed_count = Submission.objects.filter(
        respondent=user,
        status=Submission.Status.COMPLETED,
    ).count()

    return render(
        request,
        'core/overview.html',
        {
            'profile': user.profile,
            'points_balance': PointTransaction.objects.balance_for(user),
            'active_survey_count': active_survey_count,
            'survey_status_counts': survey_status_counts,
            'total_response_count': total_responses,
            'surveys_completed_count': surveys_completed_count,
            'latest_survey': owned_surveys.first(),
            'recent_earnings': PointTransaction.objects.filter(user=user).select_related('survey')[:5],
            'badge_awards': BadgeAward.objects.filter(user=user).select_related('badge')[:4],
        },
    )
