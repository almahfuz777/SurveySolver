from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .claims import prepare_pending_claim
from .models import GuestRewardClaim


def _session_key(request):
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


@require_POST
def prepare_claim(request, claim_id):
    claim = get_object_or_404(
        GuestRewardClaim.objects.select_related('submission'),
        id=claim_id,
    )
    if not prepare_pending_claim(
        claim,
        request.POST.get('claim_secret', ''),
        _session_key(request),
        request.session,
    ):
        return redirect('response_complete', submission_id=claim.submission_id)
    destination = 'account_login' if request.POST.get('destination') == 'login' else 'account_signup'
    return redirect(destination)
