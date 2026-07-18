from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from surveys.forms import SurveyMetadataForm
from surveys.models import Survey, Topic
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

    def test_survey_detail_redirects_editors_to_builder(self):
        survey = Survey.objects.create(owner=self.user, title='Redirect study', summary='Detail page routes to the builder.')
        self.client.force_login(self.user)
        response = self.client.get(reverse('survey_detail', args=[survey.id]))
        self.assertRedirects(response, reverse('survey_builder', args=[survey.id]))

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
        response = self.client.post(reverse('survey_purge', args=[survey.id]))
        self.assertRedirects(response, reverse('survey_list'))
        self.assertFalse(Survey.objects.filter(id=survey.id).exists())

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

    def test_metadata_form_limits_topics_to_five(self):
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
        self.assertIn('Select no more than five topics.', form.errors['topics'])

    def test_survey_image_size_is_limited(self):
        oversized_image = type('Upload', (), {'size': MAX_SURVEY_IMAGE_SIZE + 1})()

        with self.assertRaisesMessage(
            ValidationError,
            'Survey images must be 5 MB or smaller.',
        ):
            validate_survey_image_size(oversized_image)
