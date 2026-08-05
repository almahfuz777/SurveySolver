from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from responses.models import ResponseAuditEvent, Submission
from rewards.models import PointTransaction
from surveys import services
from surveys.builder.forms import SurveyMetadataForm
from surveys.models import Question, Survey, Topic
from surveys.publication import publish_survey
from surveys.validators import MAX_SURVEY_IMAGE_SIZE, validate_survey_image_size


class SurveyManagementTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email='owner@example.com')
        self.other_user = get_user_model().objects.create_user(email='other@example.com')
        self.topic = Topic.objects.get(slug='computer-science')

    def test_survey_pages_require_authentication(self):
        response = self.client.get(reverse('survey_list'))
        self.assertRedirects(response, f"{reverse('account_login')}?next={reverse('survey_list')}")

    def test_creator_can_create_survey_draft(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('survey_create'))
        survey = Survey.objects.get()
        self.assertRedirects(response, reverse('survey_builder', args=[survey.id]))
        self.assertEqual(survey.owner, self.user)
        self.assertEqual(survey.status, Survey.Status.DRAFT)
        self.assertEqual(survey.title, 'Untitled survey')
        self.assertTrue(survey.slug.startswith('untitled-survey-'))
        self.assertIsNotNone(survey.draft_version)

    def test_survey_list_discards_untouched_draft(self):
        self.client.force_login(self.user)
        self.client.post(reverse('survey_create'))
        survey = Survey.objects.get()

        self.client.get(reverse('survey_list'))

        self.assertFalse(Survey.objects.filter(pk=survey.pk).exists())

    def test_survey_list_keeps_draft_with_content(self):
        self.client.force_login(self.user)
        self.client.post(reverse('survey_create'))
        survey = Survey.objects.get()
        section = survey.draft_version.sections.first()
        Question.objects.create(
            section=section,
            type=Question.Type.SHORT_TEXT,
            prompt='Your name?',
        )

        self.client.get(reverse('survey_list'))

        self.assertTrue(Survey.objects.filter(pk=survey.pk).exists())

    def test_survey_list_keeps_renamed_draft(self):
        self.client.force_login(self.user)
        self.client.post(reverse('survey_create'))
        Survey.objects.update(title='My real survey')
        survey = Survey.objects.get()

        self.client.get(reverse('survey_list'))

        self.assertTrue(Survey.objects.filter(pk=survey.pk).exists())

    def test_survey_list_offers_card_and_compact_views(self):
        survey = Survey.objects.create(owner=self.user, title='View options', summary='')
        self.client.force_login(self.user)

        response = self.client.get(reverse('survey_list'))
        responses_url = reverse('creator_response_list', args=[survey.id])

        self.assertContains(response, 'data-survey-view')
        self.assertContains(response, '<option value="card">Card</option>', html=True)
        self.assertContains(response, '<option value="compact">Compact</option>', html=True)
        self.assertContains(response, 'data-survey-grid')
        self.assertContains(response, 'survey-card-summary-placeholder')
        self.assertContains(response, f'class="survey-card-body" href="{responses_url}"')
        self.assertContains(
            response,
            '<span class="survey-version-pill" aria-label="Version 1">v1</span>',
            html=True,
        )

    def test_survey_detail_redirects_editors_to_builder(self):
        survey = Survey.objects.create(owner=self.user, title='Redirect study', summary='Detail page routes to the builder.')
        self.client.force_login(self.user)
        response = self.client.get(reverse('survey_detail', args=[survey.id]))
        self.assertRedirects(response, reverse('survey_builder', args=[survey.id]))

    def test_builder_studio_pages_omit_the_global_footer(self):
        survey = Survey.objects.create(owner=self.user, title='Studio layout', summary='Footer-free editing routes.')
        self.client.force_login(self.user)

        for route_name in ('survey_builder', 'survey_edit', 'survey_preview'):
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name, args=[survey.id]))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'site-footer')

        self.assertContains(self.client.get(reverse('survey_list')), 'site-footer')

    def test_non_owner_cannot_view_or_edit_survey(self):
        survey = Survey.objects.create(owner=self.user, title='Private research', summary='Only the owner can manage this survey.')
        self.client.force_login(self.other_user)
        for url_name in ('survey_detail', 'survey_edit'):
            with self.subTest(url_name=url_name):
                self.assertEqual(self.client.get(reverse(url_name, args=[survey.id])).status_code, 404)

    def test_owner_can_soft_delete_restore_and_purge_survey(self):
        survey = Survey.objects.create(owner=self.user, title='Disposable study', summary='A survey to delete.')
        self.client.force_login(self.user)

        response = self.client.post(reverse('survey_delete', args=[survey.id]))
        self.assertRedirects(response, reverse('survey_list'))
        survey.refresh_from_db()
        self.assertIsNotNone(survey.deleted_at)
        self.assertNotContains(self.client.get(reverse('survey_list')), 'survey-management-card')

        response = self.client.post(reverse('survey_restore', args=[survey.id]))
        survey.refresh_from_db()
        self.assertIsNone(survey.deleted_at)

        self.client.post(reverse('survey_delete', args=[survey.id]))
        purge_url = reverse('survey_purge', args=[survey.id])
        confirmation_page = self.client.get(purge_url)
        rejected = self.client.post(purge_url, {'confirmation': 'DELETE'})

        self.assertContains(confirmation_page, 'DELETE Disposable study')
        self.assertEqual(rejected.status_code, 200)
        self.assertTrue(Survey.objects.filter(id=survey.id).exists())

        response = self.client.post(
            purge_url,
            {'confirmation': 'DELETE Disposable study'},
        )
        self.assertRedirects(response, reverse('survey_list'))
        self.assertFalse(Survey.objects.filter(id=survey.id).exists())

    def test_owner_can_purge_survey_with_responses_and_retain_tombstones(self):
        survey = Survey.objects.create(
            owner=self.user,
            title='Completed study',
            summary='Contains response history.',
        )
        draft = survey.draft_version
        Question.objects.create(
            section=draft.sections.get(),
            type=Question.Type.SHORT_TEXT,
            prompt='Question',
        )
        version, _ = publish_survey(survey.id, self.user, draft.revision)
        submission = Submission.objects.create(
            survey=survey,
            version=version,
            respondent=self.other_user,
            session_key_hash='a' * 64,
            presentation={'sections': []},
        )
        Submission.objects.filter(pk=submission.pk).update(
            status=Submission.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        transaction = PointTransaction.objects.create(
            user=self.other_user,
            amount=10,
            reason=PointTransaction.Reason.SURVEY_COMPLETION,
            idempotency_key=f'survey-completion:{self.other_user.id}:{survey.id}',
            survey=survey,
            submission=submission,
        )
        survey.soft_delete()
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('survey_purge', args=[survey.id]),
            {'confirmation': 'DELETE Completed study'},
        )

        self.assertRedirects(response, reverse('survey_list'))
        self.assertFalse(Survey.objects.filter(pk=survey.id).exists())
        self.assertFalse(Submission.objects.filter(pk=submission.id).exists())
        transaction.refresh_from_db()
        self.assertIsNone(transaction.survey)
        self.assertIsNone(transaction.submission)
        event = ResponseAuditEvent.objects.get(submission_id=submission.id)
        self.assertIsNone(event.survey)
        self.assertEqual(event.metadata['reason'], 'survey_deleted')

    def test_deleted_survey_is_inaccessible_and_non_owner_cannot_delete(self):
        survey = Survey.objects.create(owner=self.user, title='Hidden study', summary='Soft deleted.')
        self.client.force_login(self.user)
        self.client.post(reverse('survey_delete', args=[survey.id]))
        self.assertEqual(self.client.get(reverse('survey_builder', args=[survey.id])).status_code, 404)

        restored = Survey.objects.create(owner=self.user, title='Other users study', summary='Not yours.')
        self.client.force_login(self.other_user)
        self.assertEqual(self.client.post(reverse('survey_delete', args=[restored.id])).status_code, 404)

    def test_owner_can_rename_survey_inline(self):
        survey = Survey.objects.create(owner=self.user, title='Old name', summary='Renaming test.')
        self.client.force_login(self.user)
        response = self.client.post(reverse('survey_rename', args=[survey.id]), {'title': 'New name'})
        self.assertEqual(response.status_code, 200)
        survey.refresh_from_db()
        self.assertEqual(survey.title, 'New name')

        response = self.client.post(reverse('survey_rename', args=[survey.id]), {'title': '   '})
        self.assertEqual(response.status_code, 422)

    def test_owner_can_archive_survey(self):
        survey = Survey.objects.create(owner=self.user, title='Completed research', summary='A completed study ready for archiving.')
        self.client.force_login(self.user)
        response = self.client.post(reverse('survey_archive', args=[survey.id]))
        self.assertRedirects(response, reverse('survey_list'))
        survey.refresh_from_db()
        self.assertEqual(survey.status, Survey.Status.ARCHIVED)

    def test_owner_can_pause_and_resume_response_collection_from_settings(self):
        survey = Survey.objects.create(owner=self.user, title='Live research', summary='Collection controls.')
        draft = survey.draft_version
        _, revision = services.add_question(draft.sections.get().id, Question.Type.SHORT_TEXT, draft.revision)
        publish_survey(survey.id, self.user, revision)
        self.client.force_login(self.user)

        survey_list = self.client.get(reverse('survey_list'))
        self.assertNotContains(survey_list, 'Accept responses')
        settings = self.client.get(reverse('survey_edit', args=[survey.id]))
        self.assertContains(settings, 'Response collection')
        self.assertContains(settings, 'Accept responses')

        response = self.client.post(reverse('survey_response_collection', args=[survey.id]))
        self.assertRedirects(response, reverse('survey_edit', args=[survey.id]))
        survey.refresh_from_db()
        self.assertEqual(survey.status, Survey.Status.CLOSED)
        self.assertIsNotNone(survey.closed_at)

        self.client.post(
            reverse('survey_response_collection', args=[survey.id]),
            {'accepting': 'on'},
        )
        survey.refresh_from_db()
        self.assertEqual(survey.status, Survey.Status.PUBLISHED)
        self.assertIsNone(survey.closed_at)

    def test_non_owner_cannot_toggle_response_collection(self):
        survey = Survey.objects.create(owner=self.user, title='Owner controlled', summary='Private control.')
        self.client.force_login(self.other_user)
        response = self.client.post(reverse('survey_response_collection', args=[survey.id]))
        self.assertEqual(response.status_code, 404)

    def test_settings_replaces_archive_and_quotas_with_response_limit(self):
        survey = Survey.objects.create(owner=self.user, title='Settings study', summary='Settings content.')
        self.client.force_login(self.user)
        response = self.client.get(reverse('survey_edit', args=[survey.id]))
        self.assertContains(response, 'Response limit')
        self.assertContains(response, 'Any country')
        self.assertContains(response, 'role="combobox"')
        self.assertContains(response, 'aria-expanded="false"')
        self.assertNotContains(response, 'Response quotas')
        self.assertNotContains(response, 'Archive survey')
        self.assertContains(response, 'Changes save automatically')
        self.assertEqual(response.content.count(b' data-settings-autosave>'), 3)
        self.assertContains(response, 'data-settings-publish')
        self.assertNotContains(response, 'Save settings')
        self.assertNotContains(response, 'Save eligibility')
        self.assertNotContains(response, 'Save response limit')
        self.assertEqual(response.content.count(b'<main'), 1)
        self.assertEqual(response.content.count(b'<h1'), 1)

    def test_metadata_autosave_then_publish_updates_survey_card(self):
        survey = Survey.objects.create(owner=self.user, title='Metadata publishing', summary='Publish settings together.')
        draft = survey.draft_version
        _, revision = services.add_question(draft.sections.get().id, Question.Type.SHORT_TEXT, draft.revision)
        publish_survey(survey.id, self.user, revision)
        survey.refresh_from_db()
        next_draft = survey.draft_version
        self.client.force_login(self.user)

        settings = self.client.get(reverse('survey_edit', args=[survey.id]))
        self.assertContains(settings, 'id="survey-metadata-form"')
        response = self.client.post(
            reverse('survey_edit', args=[survey.id]),
            {
                'action': 'metadata',
                'revision': next_draft.revision,
                'topics': [self.topic.id],
                'visibility': Survey.Visibility.DISCOVERABLE,
                'identity_mode': Survey.IdentityMode.ANONYMOUS,
                'estimated_minutes': 17,
            },
            HTTP_ACCEPT='application/json',
        )

        self.assertEqual(response.status_code, 200)
        publish_response = self.client.post(
            reverse('survey_publish', args=[survey.id]),
            {'revision': response.json()['revision']},
        )
        self.assertRedirects(
            publish_response,
            reverse('survey_publish_review', args=[survey.id]),
        )
        survey.refresh_from_db()
        self.assertEqual(survey.estimated_minutes, 17)
        self.assertEqual(list(survey.topics.values_list('id', flat=True)), [self.topic.id])
        survey_list = self.client.get(reverse('survey_list'))
        self.assertContains(survey_list, '17 min')
        self.assertContains(survey_list, self.topic.name)

    def test_successful_publish_returns_to_my_surveys(self):
        survey = Survey.objects.create(
            owner=self.user,
            title='Publish redirect',
            summary='Return to the survey list after review.',
        )
        draft = survey.draft_version
        _, revision = services.add_question(
            draft.sections.get().id,
            Question.Type.SHORT_TEXT,
            draft.revision,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('survey_publish', args=[survey.id]),
            {'revision': revision},
        )

        self.assertRedirects(response, reverse('survey_list'))

    def test_versioned_settings_autosave_returns_each_new_revision(self):
        survey = Survey.objects.create(owner=self.user, title='Autosave revisions', summary='Sequential settings saves.')
        version = survey.draft_version
        self.client.force_login(self.user)

        eligibility = self.client.post(
            reverse('survey_edit', args=[survey.id]),
            {'action': 'update_eligibility', 'revision': version.revision},
            HTTP_ACCEPT='application/json',
        )
        self.assertEqual(eligibility.status_code, 200)
        response_limit = self.client.post(
            reverse('survey_edit', args=[survey.id]),
            {
                'action': 'update_response_limit',
                'revision': eligibility.json()['revision'],
                'enabled': 'on',
                'response_limit': 25,
            },
            HTTP_ACCEPT='application/json',
        )

        self.assertEqual(response_limit.status_code, 200)
        self.assertGreater(response_limit.json()['revision'], eligibility.json()['revision'])

    def test_discoverable_queryset_excludes_drafts_and_unlisted_surveys(self):
        Survey.objects.create(owner=self.user, title='Draft survey', summary='Not published yet.')
        Survey.objects.create(owner=self.user, title='Unlisted survey', summary='Published but not listed.', status=Survey.Status.PUBLISHED, visibility=Survey.Visibility.UNLISTED)
        discoverable = Survey.objects.create(owner=self.user, title='Public survey', summary='Published and discoverable.', status=Survey.Status.PUBLISHED, visibility=Survey.Visibility.DISCOVERABLE)
        self.assertEqual(list(Survey.objects.discoverable()), [discoverable])

    def test_survey_slugs_remain_unique_for_duplicate_titles(self):
        first = Survey.objects.create(
            owner=self.user,
            title='Shared title',
            summary='First survey.',
        )
        second = Survey.objects.create(
            owner=self.user,
            title='Shared title',
            summary='Second survey.',
        )

        self.assertNotEqual(first.slug, second.slug)

    def test_metadata_form_limits_topics_to_three(self):
        form = SurveyMetadataForm(
            data={
                'title': 'Over-categorized survey',
                'summary': 'A survey with too many topic selections.',
                'topics': [str(topic.id) for topic in Topic.objects.all()[:6]],
                'visibility': Survey.Visibility.DISCOVERABLE,
                'identity_mode': Survey.IdentityMode.ANONYMOUS,
                'estimated_minutes': 5,
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn('Select no more than three topics.', form.errors['topics'])

    def test_survey_image_size_is_limited(self):
        oversized_image = type('Upload', (), {'size': MAX_SURVEY_IMAGE_SIZE + 1})()

        with self.assertRaisesMessage(
            ValidationError,
            'Survey images must be 5 MB or smaller.',
        ):
            validate_survey_image_size(oversized_image)
