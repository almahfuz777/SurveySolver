from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from rewards.models import PointTransaction


class HeaderPointsBalanceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email='header@example.com',
            password='header-pass-123',
        )

    def test_header_shows_the_reward_balance_for_authenticated_users(self):
        PointTransaction.objects.create(
            user=self.user,
            amount=50,
            reason=PointTransaction.Reason.PROFILE_COMPLETION,
            idempotency_key=f'profile-completion:{self.user.pk}',
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('discover'))

        self.assertEqual(response.context['points_balance'], 50)
        self.assertContains(response, 'coin-chip')
        self.assertContains(response, '<span class="coin-chip-value">50</span>', html=False)

    def test_new_users_see_a_zero_balance(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('discover'))

        self.assertContains(response, '<span class="coin-chip-value">0</span>', html=False)

    def test_anonymous_visitors_get_no_balance_in_context(self):
        response = self.client.get(reverse('discover'))

        self.assertNotIn('points_balance', response.context)
        self.assertNotContains(response, 'coin-chip')
