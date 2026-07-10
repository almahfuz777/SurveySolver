from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from rewards.models import PointTransaction


class PointTransactionTests(TestCase):
    def test_ledger_entries_are_immutable(self):
        user = get_user_model().objects.create_user(email='points@example.com')
        entry = PointTransaction.objects.create(
            user=user,
            amount=50,
            reason=PointTransaction.Reason.PROFILE_COMPLETION,
            idempotency_key=f'profile-completion:{user.pk}',
        )

        entry.amount = 100
        with self.assertRaisesMessage(ValidationError, 'Point transactions are immutable.'):
            entry.save()

        with self.assertRaisesMessage(ValidationError, 'Point transactions are immutable.'):
            entry.delete()

        self.assertEqual(PointTransaction.objects.balance_for(user), 50)
