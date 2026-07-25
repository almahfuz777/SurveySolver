from django.utils.functional import SimpleLazyObject

from .models import PointTransaction


def points_balance(request):
    """Expose the reward ledger balance to the shared header on every page."""
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {}
    return {
        'points_balance': SimpleLazyObject(
            lambda: PointTransaction.objects.balance_for(user)
        ),
    }
