from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from responses.models import Submission
from rewards.models import PointTransaction
from surveys import services
from surveys.models import Question, Survey, Topic
from surveys.publication import publish_survey


class SurveyDiscoveryTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(email='discover-owner@example.com')
        self.topic = Topic.objects.create(
            name='Learning Science',
            slug='learning-science',
        )

    def publish_survey(
        self,
        title,
        *,
        visibility=Survey.Visibility.DISCOVERABLE,
        minutes=5,
        criteria=None,
        identity_mode=Survey.IdentityMode.ANONYMOUS,
    ):
        survey = Survey.objects.create(
            owner=self.owner,
            title=title,
            summary=f'{title} summary',
            visibility=visibility,
            estimated_minutes=minutes,
            identity_mode=identity_mode,
        )
        survey.topics.add(self.topic)
        draft = survey.draft_version
        _, revision = services.add_question(
            draft.sections.get().id,
            Question.Type.SHORT_TEXT,
            draft.revision,
        )
        if criteria:
            _, revision = services.update_eligibility(
                draft.id,
                revision,
                criteria,
            )
        version, _ = publish_survey(survey.id, self.owner, revision)
        survey.refresh_from_db()
        return survey, version

    def criteria(self, country='BD'):
        return {
            'min_age': 18,
            'max_age': 30,
            'education_levels': ['undergraduate'],
            'countries': [country],
            'genders': [],
            'employment_statuses': ['student'],
        }

    def test_public_discovery_shows_cards_points_and_screeners(self):
        open_survey, _ = self.publish_survey('Open study')
        targeted, _ = self.publish_survey('Targeted study', criteria=self.criteria())
        hidden, _ = self.publish_survey(
            'Unlisted study',
            visibility=Survey.Visibility.UNLISTED,
        )

        response = self.client.get(reverse('discover'))

        self.assertContains(response, open_survey.title)
        self.assertContains(response, targeted.title)
        self.assertEqual(len(response.context['discovery_surveys']), 2)
        self.assertContains(response, '+10 points')
        self.assertContains(response, 'Eligibility screener')
        self.assertContains(response, self.topic.name)
        self.assertContains(response, 'name="points"')
        self.assertContains(response, 'name="privacy"')
        self.assertNotContains(response, hidden.title)

    def test_guest_discovery_only_lists_anonymous_studies(self):
        anonymous, _ = self.publish_survey('Anonymous study')
        identified, _ = self.publish_survey(
            'Identified study',
            identity_mode=Survey.IdentityMode.IDENTIFIED,
        )

        response = self.client.get(reverse('discover'))

        self.assertContains(response, anonymous.title)
        self.assertNotContains(response, identified.title)
        self.assertContains(
            response,
            '<option value="anonymous" selected>Anonymous</option>',
            html=True,
        )
        self.assertContains(
            response,
            '<option value="identified" disabled>Identified</option>',
            html=True,
        )
        self.assertNotContains(response, 'Sign in to access identified studies.')

    def test_authenticated_user_can_filter_identified_studies(self):
        anonymous, _ = self.publish_survey('Anonymous study')
        identified, _ = self.publish_survey(
            'Identified study',
            identity_mode=Survey.IdentityMode.IDENTIFIED,
        )
        respondent = get_user_model().objects.create_user(email='privacy-filter@example.com')
        self.client.force_login(respondent)

        response = self.client.get(
            reverse('discover'),
            {'privacy': Survey.IdentityMode.IDENTIFIED},
        )

        self.assertContains(response, identified.title)
        self.assertNotContains(response, anonymous.title)

    def test_authenticated_discovery_uses_completed_profile_fields(self):
        eligible, _ = self.publish_survey('Bangladesh student study', criteria=self.criteria())
        ineligible, _ = self.publish_survey('United States student study', criteria=self.criteria('US'))
        respondent = get_user_model().objects.create_user(email='matched@example.com')
        profile = respondent.profile
        profile.birth_date = date(2001, 1, 1)
        profile.education_level = 'undergraduate'
        profile.country = 'BD'
        profile.employment_status = 'student'
        profile.save()
        self.client.force_login(respondent)

        response = self.client.get(reverse('discover'))

        self.assertContains(response, eligible.title)
        self.assertNotContains(response, ineligible.title)
        self.assertContains(response, 'Profile matched')

    def test_incomplete_profile_does_not_receive_targeted_surveys(self):
        unrestricted, _ = self.publish_survey('Unrestricted study')
        targeted, _ = self.publish_survey('Targeted study', criteria=self.criteria())
        respondent = get_user_model().objects.create_user(email='incomplete-match@example.com')
        self.client.force_login(respondent)

        response = self.client.get(reverse('discover'))

        self.assertContains(response, unrestricted.title)
        self.assertNotContains(response, targeted.title)

    def test_completed_and_owned_surveys_are_removed_from_feed(self):
        completed_survey, version = self.publish_survey('Completed study')
        respondent = get_user_model().objects.create_user(email='completed@example.com')
        Submission.objects.create(
            survey=completed_survey,
            version=version,
            respondent=respondent,
            session_key_hash='a' * 64,
            status=Submission.Status.COMPLETED,
            completed_at=timezone.now(),
            presentation={'sections': []},
            eligibility_data={'targeted': False},
            eligibility_checked_at=timezone.now(),
        )
        owned, _ = self.publish_survey('Originally another owner')
        owned.owner = respondent
        owned.save(update_fields=('owner', 'updated_at'))
        self.client.force_login(respondent)

        response = self.client.get(reverse('discover'))

        self.assertNotContains(response, completed_survey.title)
        self.assertNotContains(response, owned.title)

    def test_topic_and_duration_filters_are_applied_together(self):
        short, _ = self.publish_survey('Short learning study', minutes=5)
        long, _ = self.publish_survey('Long learning study', minutes=20)

        response = self.client.get(
            reverse('discover'),
            {'topic': self.topic.slug, 'duration': '5'},
        )

        self.assertContains(response, short.title)
        self.assertNotContains(response, long.title)

    def test_discovery_filters_are_live_and_page_assets_are_modular(self):
        response = self.client.get(reverse('discover'))

        self.assertContains(response, 'data-live-filters')
        self.assertContains(response, 'data-discovery-results')
        self.assertContains(response, 'css/core/discover.css')
        self.assertContains(response, 'js/pages/discover.js')

    def test_live_filter_request_returns_only_updated_results(self):
        matching, _ = self.publish_survey('Matching study', minutes=5)
        excluded, _ = self.publish_survey('Excluded study', minutes=20)

        response = self.client.get(
            reverse('discover'),
            {'duration': '5'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertTemplateUsed(response, 'core/partials/discovery_results.html')
        self.assertContains(response, matching.title)
        self.assertNotContains(response, excluded.title)
        self.assertNotContains(response, 'data-live-filters')


class DashboardMetricTests(TestCase):
    def test_dashboard_context_uses_correct_metric_sources(self):
        user = get_user_model().objects.create_user(email='metrics@example.com')
        owned = Survey.objects.create(
            owner=user,
            title='Owned survey',
            summary='Owned survey summary',
        )
        PointTransaction.objects.create(
            user=user,
            amount=50,
            reason=PointTransaction.Reason.PROFILE_COMPLETION,
            idempotency_key=f'profile-completion:{user.id}',
        )
        Submission.objects.create(
            survey=owned,
            version=owned.draft_version,
            session_key_hash='b' * 64,
            status=Submission.Status.COMPLETED,
            completed_at=timezone.now(),
            presentation={'sections': []},
        )
        self.client.force_login(user)

        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.context['active_survey_count'], 1)
        self.assertEqual(response.context['total_response_count'], 1)
        self.assertEqual(response.context['points_balance'], 50)
