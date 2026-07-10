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
        response = self.client.post(reverse('survey_create'), {'title': 'Digital wellbeing study', 'summary': 'A study about technology use and academic focus.', 'description': 'This research explores daily screen habits.', 'topics': [str(self.topic.id)], 'visibility': Survey.Visibility.DISCOVERABLE, 'identity_mode': Survey.IdentityMode.ANONYMOUS, 'estimated_minutes': 8})
        survey = Survey.objects.get()
        self.assertRedirects(response, reverse('survey_detail', args=[survey.id]))
        self.assertEqual(survey.owner, self.user)
        self.assertEqual(survey.status, Survey.Status.DRAFT)
        self.assertTrue(survey.slug.startswith('digital-wellbeing-study-'))
        self.assertEqual(list(survey.topics.all()), [self.topic])

    def test_non_owner_cannot_view_or_edit_survey(self):
        survey = Survey.objects.create(owner=self.user, title='Private research', summary='Only the owner can manage this survey.')
        self.client.force_login(self.other_user)
        for url_name in ('survey_detail', 'survey_edit'):
            with self.subTest(url_name=url_name):
                self.assertEqual(self.client.get(reverse(url_name, args=[survey.id])).status_code, 404)

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
