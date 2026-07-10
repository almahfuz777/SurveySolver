from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from responses.models import Submission
from rewards.models import BadgeAward, PointTransaction
from rewards.claims import BASE_COMPLETION_POINTS
from surveys.discovery import discover_surveys
from surveys.models import Survey, Topic


def home(request):
    topic = request.GET.get('topic', '').strip()
    try:
        duration = int(request.GET.get('duration', ''))
    except (TypeError, ValueError):
        duration = None
    if duration not in {5, 10, 20}:
        duration = None
    return render(
        request,
        'core/home.html',
        {
            'discovery_surveys': discover_surveys(
                request.user,
                topic=topic or None,
                duration=duration,
            ),
            'topics': Topic.objects.filter(is_active=True),
            'selected_topic': topic,
            'selected_duration': duration,
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
