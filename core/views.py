from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from rewards.models import PointTransaction


def home(request):
    return render(request, 'core/home.html')


@login_required
def dashboard(request):
    return render(
        request,
        'core/dashboard.html',
        {
            'profile': request.user.profile,
            'points_balance': PointTransaction.objects.balance_for(request.user),
        },
    )
