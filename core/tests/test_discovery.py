from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from responses.models import Answer, Submission
from responses.services import start_submission
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

    def test_new_demographic_dimensions_gate_targeting(self):
        criteria = {
            'regions': ['BD-13'],
            'industries': ['it'],
            'income_brackets': ['1000_2500'],
            'religions': ['islam'],
            'ethnicities': ['south_asian'],
            'languages': ['bn', 'en'],
        }
        targeted, _ = self.publish_survey('Fine-grained study', criteria=criteria)

        def make_respondent(email, **overrides):
            user = get_user_model().objects.create_user(email=email)
            profile = user.profile
            profile.region = 'BD-13'
            profile.industry = 'it'
            profile.income_bracket = '1000_2500'
            profile.religion = 'islam'
            profile.ethnicity = 'south_asian'
            profile.languages = ['bn']
            for field, value in overrides.items():
                setattr(profile, field, value)
            profile.save()
            return user

        match = make_respondent('demo-match@example.com')
        self.client.force_login(match)
        self.assertContains(self.client.get(reverse('discover')), targeted.title)

        # Wrong region → excluded, even with everything else matching.
        wrong_region = make_respondent('demo-region@example.com', region='BD-27')
        self.client.force_login(wrong_region)
        self.assertNotContains(self.client.get(reverse('discover')), targeted.title)

        # No shared language → excluded.
        wrong_lang = make_respondent('demo-lang@example.com', languages=['hi'])
        self.client.force_login(wrong_lang)
        self.assertNotContains(self.client.get(reverse('discover')), targeted.title)

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

    def test_show_completed_lists_completed_surveys_separately_with_disabled_start(self):
        completed_survey, version = self.publish_survey('Completed study')
        other_survey, _ = self.publish_survey('Other study')
        respondent = get_user_model().objects.create_user(email='show-completed@example.com')
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
        self.client.force_login(respondent)

        default_response = self.client.get(reverse('discover'))
        self.assertNotContains(default_response, completed_survey.title)

        response = self.client.get(reverse('discover'), {'show_completed': '1'})

        self.assertContains(response, completed_survey.title)
        self.assertContains(response, other_survey.title)
        self.assertEqual(len(response.context['completed_surveys']), 1)
        self.assertEqual(response.context['completed_surveys'][0], completed_survey)
        self.assertNotIn(completed_survey, response.context['discovery_surveys'])
        self.assertContains(response, 'discovery-completed-section')
        self.assertContains(response, '<button class="button button-primary button-block" type="button" disabled>Completed</button>', html=True)

    def test_guest_saved_response_is_pinned_with_progress_and_not_duplicated(self):
        survey, version = self.publish_survey('Resume this study')
        session = self.client.session
        session.save()
        submission = start_submission(
            survey,
            None,
            session.session_key,
        )
        question = version.sections.get().questions.get()
        Answer.objects.create(
            submission=submission,
            question=question,
            value='Saved answer',
        )

        response = self.client.get(reverse('discover'))

        self.assertContains(response, 'Continue where you left off')
        self.assertContains(response, survey.title)
        self.assertNotContains(response, 'resume-version')
        self.assertContains(response, '1 of 1 answered')
        self.assertContains(response, 'aria-valuenow="100"')
        self.assertContains(
            response,
            reverse('response_form', args=[submission.id]),
        )
        self.assertContains(
            response,
            reverse('response_discard', args=[submission.id]),
        )
        self.assertEqual(
            list(response.context['ongoing_submissions']),
            [submission],
        )
        self.assertNotIn(survey, response.context['discovery_surveys'])

        other_browser = self.client_class()
        self.assertNotContains(
            other_browser.get(reverse('discover')),
            'Continue where you left off',
        )

    def test_authenticated_saved_response_is_resumable_across_browsers(self):
        survey, _ = self.publish_survey('Cross-browser draft')
        respondent = get_user_model().objects.create_user(
            email='resume@example.com',
        )
        first_browser = self.client_class()
        first_browser.force_login(respondent)
        submission = start_submission(
            survey,
            respondent,
            first_browser.session.session_key,
        )
        self.client.force_login(respondent)

        response = self.client.get(reverse('discover'))

        self.assertContains(response, survey.title)
        self.assertContains(
            response,
            reverse('response_form', args=[submission.id]),
        )

    def test_live_filter_response_does_not_repeat_pinned_section(self):
        survey, _ = self.publish_survey('Pinned outside filters')
        session = self.client.session
        session.save()
        start_submission(survey, None, session.session_key)

        response = self.client.get(
            reverse('discover'),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertNotContains(response, 'Continue where you left off')
        self.assertNotContains(response, survey.title)

    def test_topic_and_duration_filters_are_applied_together(self):
        short, _ = self.publish_survey('Short learning study', minutes=5)
        long, _ = self.publish_survey('Long learning study', minutes=20)

        response = self.client.get(
            reverse('discover'),
            {'topic': self.topic.slug, 'duration': '5'},
        )

        self.assertContains(response, short.title)
        self.assertNotContains(response, long.title)

    def test_topic_filter_accepts_multiple_selected_topics(self):
        other_topic = Topic.objects.create(name='Public Health', slug='public-health-test')
        first, _ = self.publish_survey('Learning study one')
        second, version = self.publish_survey('Public health study')
        second.topics.set([other_topic])
        excluded, _ = self.publish_survey('Unrelated topic study')
        excluded.topics.clear()
        third_topic = Topic.objects.create(name='Unrelated', slug='unrelated-test')
        excluded.topics.add(third_topic)

        response = self.client.get(
            reverse('discover'),
            {'topic': [self.topic.slug, other_topic.slug]},
        )

        self.assertContains(response, first.title)
        self.assertContains(response, second.title)
        self.assertNotContains(response, excluded.title)

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
