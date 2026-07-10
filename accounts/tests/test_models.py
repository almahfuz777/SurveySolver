from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase


class UserManagerTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()

    def test_create_user_uses_normalized_email_as_identity(self):
        user = self.user_model.objects.create_user(
            email='  Researcher@Example.COM ',
            password='safe-test-password',
        )

        self.assertEqual(user.email, 'researcher@example.com')
        self.assertTrue(user.check_password('safe-test-password'))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(str(user), user.email)

    def test_create_user_requires_email(self):
        with self.assertRaisesMessage(ValueError, 'An email address is required.'):
            self.user_model.objects.create_user(email='', password='password')

    def test_create_superuser_sets_required_permissions(self):
        user = self.user_model.objects.create_superuser(
            email='admin@example.com',
            password='safe-test-password',
        )

        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)

    def test_email_is_unique(self):
        self.user_model.objects.create_user(
            email='member@example.com',
            password='safe-test-password',
        )

        with self.assertRaises(IntegrityError):
            self.user_model.objects.create(email='MEMBER@example.com')
