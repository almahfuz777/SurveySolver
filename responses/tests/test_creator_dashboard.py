from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from surveys.models import Question, Survey
from surveys.publication import publish_survey

from responses.models import Submission


class CreatorResponseDashboardTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(email='dashboard-owner@example.com')
        self.respondent = get_user_model().objects.create_user(email='private-user@example.com')
        self.survey = Survey.objects.create(
            owner=self.owner,
            title='Dashboard study',
            summary='Creator response dashboard fixtures.',
        )
        draft = self.survey.draft_version
        Question.objects.create(
            section=draft.sections.get(),
            type=Question.Type.SHORT_TEXT,
            prompt='Describe your experience',
            required=True,
            order=1,
        )
        self.version, _ = publish_survey(self.survey.id, self.owner, draft.revision)
        self.survey.refresh_from_db()
        self.question = self.version.sections.get().questions.get()

    def complete_response(self, *, identity_data=None):
        client = self.client_class()
        client.force_login(self.respondent)
        start_data = {}
        if identity_data:
            start_data = {
                'identity_name': identity_data['name'],
                'identity_email': identity_data['email'],
                'identity_consent': 'yes',
            }
        client.post(reverse('respond_survey', args=[self.survey.slug]), start_data)
        submission = Submission.objects.get()
        client.post(
            reverse('response_form', args=[submission.id]),
            {f'q_{self.question.id}': 'A detailed response'},
        )
        submission.refresh_from_db()
        return submission

    def test_owner_sees_response_metrics_and_answer_detail(self):
        submission = self.complete_response()
        self.client.force_login(self.owner)

        response = self.client.get(reverse('creator_response_list', args=[self.survey.id]))
        detail = self.client.get(
            reverse('creator_response_detail', args=[self.survey.id, submission.id]),
        )

        self.assertEqual(response.context['metrics']['starts'], 1)
        self.assertEqual(response.context['metrics']['completions'], 1)
        self.assertEqual(response.context['metrics']['completion_rate'], 100)
        self.assertContains(detail, 'Describe your experience')
        self.assertContains(detail, 'A detailed response')

    def test_anonymous_mode_never_exposes_platform_account_identity(self):
        submission = self.complete_response()
        self.client.force_login(self.owner)

        response = self.client.get(reverse('creator_response_list', args=[self.survey.id]))
        detail = self.client.get(
            reverse('creator_response_detail', args=[self.survey.id, submission.id]),
        )

        self.assertContains(response, 'Anonymous')
        self.assertNotContains(response, self.respondent.email)
        self.assertContains(detail, 'Platform account data is hidden')
        self.assertNotContains(detail, self.respondent.email)

    def test_identified_mode_shows_only_explicitly_consented_identity(self):
        self.survey.identity_mode = Survey.IdentityMode.IDENTIFIED
        self.survey.save(update_fields=('identity_mode', 'updated_at'))
        submission = self.complete_response(
            identity_data={'name': 'Shared Name', 'email': 'shared@example.com'},
        )
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse('creator_response_detail', args=[self.survey.id, submission.id]),
        )

        self.assertContains(response, 'Shared Name')
        self.assertContains(response, 'shared@example.com')
        self.assertNotContains(response, self.respondent.email)

    def test_dashboard_is_owner_scoped(self):
        submission = self.complete_response()
        outsider = get_user_model().objects.create_user(email='outsider@example.com')

        anonymous = self.client.get(reverse('creator_response_list', args=[self.survey.id]))
        self.assertRedirects(
            anonymous,
            f"{reverse('account_login')}?next={reverse('creator_response_list', args=[self.survey.id])}",
        )
        self.client.force_login(outsider)
        list_response = self.client.get(reverse('creator_response_list', args=[self.survey.id]))
        detail_response = self.client.get(
            reverse('creator_response_detail', args=[self.survey.id, submission.id]),
        )

        self.assertEqual(list_response.status_code, 404)
        self.assertEqual(detail_response.status_code, 404)

    def test_response_table_is_paginated(self):
        for index in range(26):
            Submission.objects.create(
                survey=self.survey,
                version=self.version,
                session_key_hash=f'{index:064d}',
                presentation={'sections': []},
                eligibility_data={'targeted': False},
            )
        self.client.force_login(self.owner)

        first_page = self.client.get(reverse('creator_response_list', args=[self.survey.id]))
        second_page = self.client.get(
            reverse('creator_response_list', args=[self.survey.id]),
            {'page': 2},
        )

        self.assertEqual(first_page.context['page_obj'].paginator.count, 26)
        self.assertEqual(len(first_page.context['page_obj'].object_list), 25)
        self.assertEqual(len(second_page.context['page_obj'].object_list), 1)
