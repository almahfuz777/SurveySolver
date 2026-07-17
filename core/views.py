from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from responses.models import Submission
from rewards.models import BadgeAward, PointTransaction
from rewards.claims import BASE_COMPLETION_POINTS
from surveys.discovery import discover_surveys
from surveys.models import Survey, Topic


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
def dashboard(request):
    owned_surveys = Survey.objects.owned_by(request.user).prefetch_related('topics')
    total_responses = Submission.objects.filter(
        survey__owner=request.user,
        status=Submission.Status.COMPLETED,
    ).count()
    return render(
        request,
        'core/dashboard.html',
        {
            'profile': request.user.profile,
            'points_balance': PointTransaction.objects.balance_for(request.user),
            'active_survey_count': owned_surveys.exclude(
                status=Survey.Status.ARCHIVED,
            ).count(),
            'total_response_count': total_responses,
            'recent_surveys': owned_surveys[:4],
            'badge_awards': BadgeAward.objects.filter(user=request.user).select_related('badge')[:4],
        },
    )
