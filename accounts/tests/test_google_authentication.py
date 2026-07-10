from urllib.parse import urlparse

from django.conf import settings
from django.test import TestCase
from django.urls import reverse


class GoogleAuthenticationTests(TestCase):
    def test_google_provider_uses_required_environment_configuration(self):
        app = settings.SOCIALACCOUNT_PROVIDERS['google']['APP']

        self.assertTrue(app['client_id'])
        self.assertTrue(app['secret'])
        self.assertEqual(app['key'], '')

    def test_login_and_signup_offer_google_authentication(self):
        for url_name in ('account_login', 'account_signup'):
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))

                self.assertContains(response, 'Continue with Google')
                self.assertContains(response, reverse('google_login'))

    def test_google_login_starts_with_post_request(self):
        get_response = self.client.get(reverse('google_login'))
        post_response = self.client.post(reverse('google_login'))

        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(post_response.status_code, 302)
        self.assertEqual(urlparse(post_response['Location']).netloc, 'accounts.google.com')
