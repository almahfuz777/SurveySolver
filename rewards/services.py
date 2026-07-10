from django.db import transaction

from .models import PointTransaction


PROFILE_COMPLETION_BONUS = 50


@transaction.atomic
def award_profile_completion_bonus(profile):
    if not profile.is_complete:
        return None, False

    return PointTransaction.objects.get_or_create(
        idempotency_key=f'profile-completion:{profile.user_id}',
        defaults={
            'user': profile.user,
            'amount': PROFILE_COMPLETION_BONUS,
            'reason': PointTransaction.Reason.PROFILE_COMPLETION,
        },
    )
