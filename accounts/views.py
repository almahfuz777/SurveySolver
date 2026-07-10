from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render

from rewards.services import award_profile_completion_bonus

from .forms import ResearchProfileForm, UserNameForm


@login_required
def profile_detail(request):
    return render(request, 'accounts/profile_detail.html')


@login_required
def profile_edit(request):
    profile = request.user.profile
    if request.method == 'POST':
        user_form = UserNameForm(request.POST, instance=request.user)
        profile_form = ResearchProfileForm(request.POST, instance=profile)
        if user_form.is_valid() and profile_form.is_valid():
            with transaction.atomic():
                user_form.save()
                profile = profile_form.save()
                _, bonus_awarded = award_profile_completion_bonus(profile)

            if bonus_awarded:
                messages.success(request, 'Profile complete — 50 reward points added.')
            else:
                messages.success(request, 'Your research profile was updated.')
            return redirect('profile_detail')
    else:
        user_form = UserNameForm(instance=request.user)
        profile_form = ResearchProfileForm(instance=profile)

    return render(
        request,
        'accounts/profile_edit.html',
        {'user_form': user_form, 'profile_form': profile_form},
    )
