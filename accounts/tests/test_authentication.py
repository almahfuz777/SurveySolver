from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AuthenticationFlowTests(TestCase):
    password = 'correct-horse-battery-staple'

    def test_account_entry_pages_render(self):
        for url_name in (
            'account_login',
            'account_signup',
            'account_reset_password',
        ):
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'SurveySolver')

    def test_signup_creates_email_only_user_and_requests_verification(self):
        response = self.client.post(
            reverse('account_signup'),
            {
                'email': 'new.researcher@example.com',
                'password1': self.password,
                'password2': self.password,
            },
        )

        self.assertRedirects(response, reverse('account_email_verification_sent'))
        user = get_user_model().objects.get(email='new.researcher@example.com')
        self.assertFalse(EmailAddress.objects.get(user=user).verified)
        self.assertEqual(len(mail.outbox), 1)

    def test_verified_user_can_sign_in_with_email(self):
        user = get_user_model().objects.create_user(
            email='verified@example.com',
            password=self.password,
        )
        EmailAddress.objects.create(
            user=user,
            email=user.email,
            primary=True,
            verified=True,
        )

        response = self.client.post(
            reverse('account_login'),
            {'login': user.email, 'password': self.password},
        )

        self.assertRedirects(response, reverse('account_email'))
        self.assertEqual(self.client.session['_auth_user_id'], str(user.pk))

    def test_signup_does_not_duplicate_existing_email(self):
        user = get_user_model().objects.create_user(
            email='member@example.com',
            password=self.password,
        )
        EmailAddress.objects.create(
            user=user,
            email=user.email,
            primary=True,
            verified=True,
        )

        response = self.client.post(
            reverse('account_signup'),
            {
                'email': 'MEMBER@example.com',
                'password1': self.password,
                'password2': self.password,
            },
        )

        self.assertRedirects(response, reverse('account_email_verification_sent'))
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_password_reset_sends_email_for_verified_account(self):
        user = get_user_model().objects.create_user(
            email='reset@example.com',
            password=self.password,
        )
        EmailAddress.objects.create(
            user=user,
            email=user.email,
            primary=True,
            verified=True,
        )

        response = self.client.post(
            reverse('account_reset_password'),
            {'email': user.email},
        )

        self.assertRedirects(response, reverse('account_reset_password_done'))
        self.assertEqual(len(mail.outbox), 1)
