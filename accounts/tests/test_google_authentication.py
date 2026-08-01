import copy
from urllib.parse import urlparse

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse


def _providers_with_placeholder_credentials():
    """The project's real provider settings with placeholder secrets substituted in.

    Everything except the credentials still comes from settings.py, so these tests cover the
    actual OAuth configuration without requiring a populated .env on CI or a clean checkout.
    """
    providers = copy.deepcopy(settings.SOCIALACCOUNT_PROVIDERS)
    providers['google']['APP'].update(client_id='test-client-id', secret='test-secret')
    return providers


@override_settings(SOCIALACCOUNT_PROVIDERS=_providers_with_placeholder_credentials())
class GoogleAuthenticationTests(TestCase):
    def test_google_provider_requests_pkce_and_only_basic_scopes(self):
        provider = settings.SOCIALACCOUNT_PROVIDERS['google']

        self.assertEqual(provider['SCOPE'], ['profile', 'email'])
        self.assertEqual(provider['AUTH_PARAMS'], {'access_type': 'online'})
        self.assertTrue(provider['OAUTH_PKCE_ENABLED'])
        self.assertTrue(provider['EMAIL_AUTHENTICATION'])
        # Google authenticates with client_id/secret alone, so `key` stays empty.
        self.assertEqual(provider['APP']['key'], '')

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
