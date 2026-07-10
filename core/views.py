from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from rewards.models import PointTransaction
from surveys.models import Survey


def home(request):
    return render(request, 'core/home.html')


@login_required
def dashboard(request):
    owned_surveys = Survey.objects.owned_by(request.user).prefetch_related('topics')
    return render(
        request,
        'core/dashboard.html',
        {
            'profile': request.user.profile,
            'points_balance': PointTransaction.objects.balance_for(request.user),
            'active_survey_count': owned_surveys.exclude(
                status=Survey.Status.ARCHIVED,
            ).count(),
            'recent_surveys': owned_surveys[:4],
        },
    )
