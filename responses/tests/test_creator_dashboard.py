from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from rewards.models import PointTransaction
from surveys.models import Question, Survey
from surveys.publication import publish_survey

from responses.models import Answer, ResponseAuditEvent, Submission


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

    def completed_response_with_answer(self, value, *, session_character='z'):
        submission = Submission.objects.create(
            survey=self.survey,
            version=self.version,
            session_key_hash=session_character * 64,
            presentation={'sections': []},
            eligibility_data={'targeted': False},
        )
        Answer.objects.create(
            submission=submission,
            question=self.question,
            value=value,
        )
        completed_at = timezone.now()
        Submission.objects.filter(pk=submission.pk).update(
            status=Submission.Status.COMPLETED,
            started_at=completed_at - timedelta(minutes=2),
            completed_at=completed_at,
        )
        return Submission.objects.get(pk=submission.pk)

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

    def test_invalid_negative_duration_is_not_reported(self):
        submission = self.complete_response()
        Submission.objects.filter(pk=submission.pk).update(
            started_at=submission.completed_at + timedelta(minutes=5),
        )
        self.client.force_login(self.owner)

        response = self.client.get(reverse('creator_response_list', args=[self.survey.id]))

        self.assertIsNone(response.context['metrics']['median_duration_seconds'])
        self.assertEqual(response.context['page_obj'].object_list[0].duration_display, '—')

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

    def test_filters_search_and_column_selection_apply_to_current_result_set(self):
        submission = self.complete_response()
        Submission.objects.create(
            survey=self.survey,
            version=self.version,
            session_key_hash='c' * 64,
            presentation={'sections': []},
        )
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse('creator_response_list', args=[self.survey.id]),
            {
                'activity-version': str(self.version.id),
                'activity-date_from': timezone.localdate().isoformat(),
                'activity-date_to': timezone.localdate().isoformat(),
                'activity-completion': Submission.Status.COMPLETED,
                'activity-source': Submission.Source.DIRECT,
                'activity-eligibility': 'eligible',
                'activity-exclusion': 'included',
                'activity-search': 'detailed response',
                'activity-columns': ['status', 'duration'],
            },
        )

        self.assertEqual(response.context['page_obj'].paginator.count, 1)
        self.assertEqual(response.context['page_obj'].object_list[0].id, submission.id)
        self.assertEqual(response.context['selected_columns'], ['status', 'duration'])
        self.assertNotContains(response, '<th scope="col">Version</th>', html=True)

    def test_response_sheet_filters_and_sorts_answer_columns(self):
        first = self.complete_response()
        second = self.completed_response_with_answer('Zebra response')
        self.client.force_login(self.owner)
        url = reverse('creator_response_list', args=[self.survey.id])

        filtered = self.client.get(
            url,
            {
                f'answer_{self.question.id}': 'zebra',
                'dashboard_view': 'sheet',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        sorted_response = self.client.get(
            url,
            {
                'sheet_sort': str(self.question.id),
                'sheet_direction': 'desc',
            },
        )

        self.assertTemplateUsed(
            filtered,
            'responses/partials/response_sheet.html',
        )
        self.assertEqual(filtered.context['responses_page'].paginator.count, 1)
        self.assertEqual(filtered.context['responses_page'].object_list[0].id, second.id)
        self.assertContains(
            filtered,
            reverse(
                'creator_response_detail',
                args=[self.survey.id, second.id],
            ),
        )
        self.assertEqual(
            [submission.id for submission in sorted_response.context['responses_page']],
            [second.id, first.id],
        )

    def test_exclude_and_include_actions_are_audited(self):
        submission = self.complete_response()
        self.client.force_login(self.owner)
        action_url = reverse(
            'creator_response_exclusion',
            args=[self.survey.id, submission.id],
        )

        excluded = self.client.post(
            action_url,
            {'action': 'exclude', 'reason': 'Failed attention check'},
        )

        self.assertRedirects(
            excluded,
            reverse('creator_response_detail', args=[self.survey.id, submission.id]),
        )
        submission.refresh_from_db()
        self.assertTrue(submission.is_excluded)
        self.assertEqual(submission.exclusion_reason, 'Failed attention check')
        event = ResponseAuditEvent.objects.get()
        self.assertEqual(event.action, ResponseAuditEvent.Action.EXCLUDED)
        self.assertEqual(event.metadata['reason'], 'Failed attention check')
        default_list = self.client.get(reverse('creator_response_list', args=[self.survey.id]))
        excluded_list = self.client.get(
            reverse('creator_response_list', args=[self.survey.id]),
            {'activity-exclusion': 'excluded'},
        )
        self.assertEqual(default_list.context['page_obj'].paginator.count, 0)
        self.assertEqual(excluded_list.context['page_obj'].paginator.count, 1)

        self.client.post(action_url, {'action': 'include'})
        submission.refresh_from_db()
        self.assertFalse(submission.is_excluded)
        self.assertEqual(
            ResponseAuditEvent.objects.filter(action=ResponseAuditEvent.Action.INCLUDED).count(),
            1,
        )

    def test_permanent_deletion_requires_confirmation_and_preserves_audit_and_ledger(self):
        submission = self.complete_response()
        transaction = PointTransaction.objects.get(submission=submission)
        self.client.force_login(self.owner)
        delete_url = reverse(
            'creator_response_delete',
            args=[self.survey.id, submission.id],
        )

        rejected = self.client.post(delete_url, {'confirmation': 'delete'})
        self.assertEqual(rejected.status_code, 200)
        self.assertTrue(Submission.objects.filter(pk=submission.id).exists())

        deleted = self.client.post(delete_url, {'confirmation': 'DELETE'})

        self.assertRedirects(deleted, reverse('creator_response_list', args=[self.survey.id]))
        self.assertFalse(Submission.objects.filter(pk=submission.id).exists())
        event = ResponseAuditEvent.objects.get(action=ResponseAuditEvent.Action.DELETED)
        self.assertEqual(event.submission_id, submission.id)
        transaction.refresh_from_db()
        self.assertIsNone(transaction.submission)
        self.assertEqual(transaction.metadata['submission_id'], str(submission.id))
