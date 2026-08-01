from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Profile
from rewards.models import PointTransaction


class ProfileTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email='profile@example.com',
            password='safe-test-password',
        )

    def test_profile_is_created_with_user(self):
        self.assertEqual(self.user.profile.completion_percentage, 0)
        self.assertFalse(self.user.profile.is_complete)

    def test_profile_pages_require_authentication(self):
        for url_name in ('profile_detail', 'profile_edit'):
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))

                self.assertRedirects(
                    response,
                    f"{reverse('account_login')}?next={reverse(url_name)}",
                )

    def test_completing_profile_awards_bonus_once(self):
        self.client.force_login(self.user)
        data = {
            'first_name': 'Amina',
            'last_name': 'Rahman',
            'birth_date': date(2000, 4, 8).isoformat(),
            'gender': 'other',
            'country': 'BD',
            'education_level': 'postgraduate',
            'field_of_study': 'computer_science',
            'employment_status': 'student',
            'occupation': '',
            'institution': 'Example University',
            'research_interests': ['mental-health', 'computer-science'],
        }

        first_response = self.client.post(reverse('profile_edit'), data)
        second_response = self.client.post(reverse('profile_edit'), data)

        self.assertRedirects(first_response, reverse('profile_detail'))
        self.assertRedirects(second_response, reverse('profile_detail'))
        self.user.refresh_from_db()
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.get_full_name(), 'Amina Rahman')
        self.assertEqual(self.user.profile.completion_percentage, 100)
        transaction = PointTransaction.objects.get(user=self.user)
        self.assertEqual(transaction.amount, 50)
        self.assertEqual(PointTransaction.objects.count(), 1)

    def test_partial_profile_does_not_award_bonus(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('profile_edit'),
            {'first_name': 'Amina', 'last_name': 'Rahman'},
        )

        self.assertRedirects(response, reverse('profile_detail'))
        self.user.refresh_from_db()
        self.assertGreater(self.user.profile.completion_percentage, 0)
        self.assertFalse(PointTransaction.objects.exists())

    def test_profile_saves_region_and_languages(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('profile_edit'),
            {
                'first_name': 'Amina',
                'last_name': 'Rahman',
                'country': 'BD',
                'region': 'BD-13',
                'languages': ['bn', 'en'],
                'industry': 'it',
                'income_bracket': '1000_2500',
                'religion': 'islam',
                'ethnicity': 'south_asian',
            },
        )

        self.assertRedirects(response, reverse('profile_detail'))
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.region, 'BD-13')
        self.assertEqual(sorted(self.user.profile.languages), ['bn', 'en'])
        self.assertEqual(self.user.profile.industry, 'it')

    def test_region_must_match_selected_country(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('profile_edit'),
            {'country': 'US', 'region': 'BD-13'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Choose a region inside your selected country.')

    def test_gender_choices_are_limited_to_man_woman_and_other(self):
        self.assertEqual(
            list(Profile.Gender.choices),
            [('man', 'Man'), ('woman', 'Woman'), ('other', 'Other')],
        )
