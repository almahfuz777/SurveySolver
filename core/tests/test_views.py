from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from responses.models import Submission
from rewards.models import PointTransaction
from surveys.models import Survey


class CorePageTests(TestCase):
    def test_home_is_public(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<title>Home | SurveySolver</title>', html=True)
        self.assertContains(response, 'Research deserves')
        self.assertContains(response, 'better responses.')
        self.assertContains(response, 'For researchers and educators')
        self.assertContains(response, 'For respondents')
        self.assertContains(response, 'Join SurveySolver', count=1)
        self.assertContains(response, reverse('discover'))
        self.assertContains(response, 'Privacy policy')
        self.assertContains(response, 'href="#"', count=4)


class MyResponsesTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email='respondent@example.com',
            password='safe-test-password',
        )
        self.owner = get_user_model().objects.create_user(email='owner@example.com')

    def complete_survey(self, title, *, points=None, completed_at=None):
        survey = Survey.objects.create(
            owner=self.owner,
            title=title,
            summary=f'{title} summary',
        )
        submission = Submission.objects.create(
            survey=survey,
            version=survey.draft_version,
            respondent=self.user,
            session_key_hash='a' * 64,
            status=Submission.Status.COMPLETED,
            completed_at=completed_at or timezone.now(),
            presentation={'sections': []},
        )
        if points:
            PointTransaction.objects.create(
                user=self.user,
                survey=survey,
                submission=submission,
                amount=points,
                reason=PointTransaction.Reason.SURVEY_COMPLETION,
                idempotency_key=f'survey-completion:{self.user.id}:{survey.id}',
            )
        return survey, submission

    def test_requires_authentication(self):
        response = self.client.get(reverse('my_responses'))

        self.assertRedirects(
            response,
            f"{reverse('account_login')}?next={reverse('my_responses')}",
        )

    def test_page_reports_completions_and_points(self):
        survey, _ = self.complete_survey('Sleep habits study', points=10)
        self.client.force_login(self.user)

        response = self.client.get(reverse('my_responses'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/my_responses.html')
        self.assertEqual(response.context['surveys_completed_count'], 1)
        self.assertEqual(response.context['points_balance'], 10)
        self.assertContains(response, survey.title)
        self.assertContains(response, '+10')

    def test_creator_metrics_are_not_repeated_here(self):
        Survey.objects.create(
            owner=self.user,
            title='My own study',
            summary='Owned survey summary',
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('my_responses'))

        # Owned surveys and responses received belong to My surveys.
        for key in ('active_survey_count', 'survey_status_counts', 'total_response_count'):
            self.assertNotIn(key, response.context)
        self.assertNotContains(response, 'My own study')

    def test_completion_without_points_is_still_listed(self):
        survey, _ = self.complete_survey('Unrewarded study')
        self.client.force_login(self.user)

        response = self.client.get(reverse('my_responses'))

        self.assertEqual(response.context['surveys_completed_count'], 1)
        self.assertEqual(response.context['points_balance'], 0)
        self.assertContains(response, survey.title)
        self.assertEqual(response.context['completed_page'][0].points_earned, 0)

    def test_history_can_be_sorted_oldest_first(self):
        older, _ = self.complete_survey(
            'Older study',
            completed_at=timezone.now() - timedelta(days=2),
        )
        newer, _ = self.complete_survey('Newer study')
        self.client.force_login(self.user)

        newest_first = self.client.get(reverse('my_responses'))
        oldest_first = self.client.get(reverse('my_responses'), {'sort': 'oldest'})

        self.assertEqual(newest_first.context['completed_page'][0].survey, newer)
        self.assertEqual(oldest_first.context['completed_page'][0].survey, older)

    def test_other_respondents_completions_are_excluded(self):
        stranger = get_user_model().objects.create_user(email='stranger@example.com')
        survey = Survey.objects.create(
            owner=self.owner,
            title='Someone elses response',
            summary='Someone elses summary',
        )
        Submission.objects.create(
            survey=survey,
            version=survey.draft_version,
            respondent=stranger,
            session_key_hash='c' * 64,
            status=Submission.Status.COMPLETED,
            completed_at=timezone.now(),
            presentation={'sections': []},
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('my_responses'))

        self.assertEqual(response.context['surveys_completed_count'], 0)
        self.assertNotContains(response, survey.title)

    def test_empty_state_points_to_discovery(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('my_responses'))

        self.assertContains(response, 'haven’t completed a survey yet')
        self.assertContains(response, reverse('discover'))

    def test_badges_are_advertised_as_unbuilt(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('my_responses'))

        self.assertContains(response, 'Coming soon')
