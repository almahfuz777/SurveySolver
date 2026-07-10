from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class CorePageTests(TestCase):
    def test_home_is_public(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Research deserves')
        self.assertContains(response, 'better responses.')

    def test_dashboard_requires_authentication(self):
        response = self.client.get(reverse('dashboard'))

        self.assertRedirects(
            response,
            f"{reverse('account_login')}?next={reverse('dashboard')}",
        )

    def test_authenticated_user_can_open_dashboard(self):
        user = get_user_model().objects.create_user(
            email='researcher@example.com',
            password='safe-test-password',
        )
        self.client.force_login(user)

        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Welcome to your research workspace')
