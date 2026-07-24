from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from surveys import services
from surveys.models import Question, Survey


class BuilderTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email='builder-owner@example.com')
        self.survey = Survey.objects.create(
            owner=self.user,
            title='Builder study',
            summary='A questionnaire builder test survey.',
        )
        self.version = self.survey.draft_version
        self.section = self.version.sections.get()

    def test_builder_is_owner_scoped_and_renders_question_palette(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('survey_builder', args=[self.survey.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add question')
        self.assertContains(response, 'Short text')
        self.assertContains(response, 'autosave-form survey-header-form')
        self.assertContains(
            response,
            reverse('survey_builder_header_update', args=[self.survey.id]),
        )
        self.assertContains(
            response,
            reverse('survey_banner_update', args=[self.survey.id]),
        )
        self.assertNotContains(response, 'headerForm.submit()')

    def test_builder_renders_resolved_choice_question_without_queryset_errors(self):
        question, _ = services.add_question(
            self.section.id,
            Question.Type.SINGLE_CHOICE,
            self.version.revision,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse('survey_builder', args=[self.survey.id]),
            {'question': question.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Option 1')

    def test_builder_defaults_to_the_first_question_but_honours_deselection(self):
        question, _ = services.add_question(
            self.section.id,
            Question.Type.SHORT_TEXT,
            self.version.revision,
        )
        self.client.force_login(self.user)
        url = reverse('survey_builder', args=[self.survey.id])

        default = self.client.get(url)
        deselected = self.client.get(url, {'question': 'none'})

        # No parameter still lands on the first question.
        self.assertContains(default, 'data-selected-card')
        self.assertNotContains(default, 'Select a question to edit')
        # `?question=none` is an explicit empty selection.
        self.assertEqual(deselected.status_code, 200)
        self.assertNotContains(deselected, 'data-selected-card')
        self.assertContains(deselected, 'Select a question to edit')
        self.assertContains(deselected, str(question.prompt))

    def test_builder_marks_questions_changed_since_the_last_publication(self):
        from surveys.publication import publish_survey

        first, revision = services.add_question(
            self.section.id,
            Question.Type.SHORT_TEXT,
            self.version.revision,
        )
        services.add_question(self.section.id, Question.Type.SHORT_TEXT, revision)
        self.survey.refresh_from_db()
        _, draft = publish_survey(
            self.survey.id,
            self.user,
            self.survey.draft_version.revision,
        )
        self.client.force_login(self.user)
        url = reverse('survey_builder', args=[self.survey.id])

        # Draft matches the live version, so nothing is marked.
        self.assertNotContains(self.client.get(url, {'question': 'none'}), 'rv-change-bar')

        draft_first = draft.sections.get().questions.get(identity_id=first.identity_id)
        _, revision = services.update_question(
            draft_first.id,
            draft.revision,
            {
                'type': draft_first.type,
                'prompt': 'Edited after publishing',
                'help_text': '',
                'required': False,
                'randomize_choices': False,
            },
            draft_first.config,
            [],
            [],
        )
        services.add_question(draft.sections.get().id, Question.Type.LONG_TEXT, revision)

        response = self.client.get(url, {'question': 'none'})

        self.assertContains(response, 'data-change="changed"', count=1)
        self.assertContains(response, 'data-change="added"', count=1)

    def test_builder_header_autosave_updates_copy_without_full_settings_payload(self):
        self.survey.estimated_minutes = 10
        self.survey.save(update_fields=('estimated_minutes', 'updated_at'))
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('survey_builder_header_update', args=[self.survey.id]),
            {
                'title': self.survey.title,
                'summary': f'{self.survey.summary}.',
            },
            HTTP_ACCEPT='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.survey.refresh_from_db()
        self.assertEqual(
            self.survey.summary,
            'A questionnaire builder test survey..',
        )
        self.assertEqual(self.survey.estimated_minutes, 10)
        self.assertEqual(self.survey.visibility, Survey.Visibility.DISCOVERABLE)
        self.assertEqual(self.survey.identity_mode, Survey.IdentityMode.ANONYMOUS)

    def test_builder_header_autosave_returns_field_errors_as_json(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('survey_builder_header_update', args=[self.survey.id]),
            {'title': '', 'summary': self.survey.summary},
            HTTP_ACCEPT='application/json',
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn('title', response.json()['errors'])
        self.survey.refresh_from_db()
        self.assertEqual(self.survey.title, 'Builder study')

    def test_builder_cover_upload_does_not_use_full_settings_form(self):
        image_data = BytesIO()
        Image.new('RGB', (2, 2), color='blue').save(image_data, format='PNG')
        upload = SimpleUploadedFile(
            'cover.png',
            image_data.getvalue(),
            content_type='image/png',
        )
        self.client.force_login(self.user)

        with TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            response = self.client.post(
                reverse('survey_banner_update', args=[self.survey.id]),
                {'banner': upload},
            )

            self.assertRedirects(
                response,
                reverse('survey_builder', args=[self.survey.id]),
            )
            self.survey.refresh_from_db()
            self.assertTrue(self.survey.banner.name.endswith('cover.png'))

    def test_question_mutations_increment_version_revision(self):
        question, revision = services.add_question(
            self.section.id,
            Question.Type.SHORT_TEXT,
            self.version.revision,
        )

        self.assertEqual(revision, 2)
        self.assertEqual(question.identity.order, 1)
        self.assertEqual(question.prompt, 'Untitled question')

        with self.assertRaises(services.StaleVersionError):
            services.add_question(
                self.section.id,
                Question.Type.DATE,
                expected_revision=1,
            )

    def test_questions_can_be_reordered_without_constraint_collisions(self):
        first, revision = services.add_question(
            self.section.id,
            Question.Type.SHORT_TEXT,
            self.version.revision,
        )
        second, revision = services.add_question(
            self.section.id,
            Question.Type.LONG_TEXT,
            revision,
        )

        services.move_question(second.id, revision, 'up')

        first.identity.refresh_from_db()
        second.identity.refresh_from_db()
        self.assertEqual((second.identity.order, first.identity.order), (1, 2))

    def test_add_question_after_inserts_and_shifts_tail(self):
        first, revision = services.add_question(self.section.id, Question.Type.SHORT_TEXT, self.version.revision)
        second, revision = services.add_question(self.section.id, Question.Type.LONG_TEXT, revision)

        inserted, revision = services.add_question(
            self.section.id, Question.Type.NUMBER, revision, after_order=first.identity.order
        )

        second.identity.refresh_from_db()
        self.assertEqual(inserted.identity.order, 2)
        self.assertEqual(second.identity.order, 3)

    def test_duplicate_question_clones_choices_after_original(self):
        original, revision = services.add_question(self.section.id, Question.Type.SINGLE_CHOICE, self.version.revision)
        tail, revision = services.add_question(self.section.id, Question.Type.SHORT_TEXT, revision)

        clone, revision = services.duplicate_question(original.id, revision)

        tail.identity.refresh_from_db()
        self.assertEqual(clone.identity.order, original.identity.order + 1)
        self.assertEqual(tail.identity.order, 3)
        self.assertEqual(clone.type, original.type)
        self.assertEqual(
            list(clone.choices.order_by('identity__order').values_list('label', flat=True)),
            list(original.choices.order_by('identity__order').values_list('label', flat=True)),
        )
        self.assertNotEqual(clone.id, original.id)

    def test_reorder_question_moves_across_sections(self):
        other, revision = services.add_section(self.version.id, self.version.revision)
        first, revision = services.add_question(self.section.id, Question.Type.SHORT_TEXT, revision)
        second, revision = services.add_question(self.section.id, Question.Type.LONG_TEXT, revision)

        services.reorder_question(first.id, revision, other.id, 0)

        first.identity.refresh_from_db()
        second.identity.refresh_from_db()
        self.assertEqual(first.identity.section_identity_id, other.identity_id)
        self.assertEqual(first.identity.order, 1)
        self.assertEqual(second.identity.order, 1)

    def test_reorder_question_within_section(self):
        first, revision = services.add_question(self.section.id, Question.Type.SHORT_TEXT, self.version.revision)
        second, revision = services.add_question(self.section.id, Question.Type.LONG_TEXT, revision)
        third, revision = services.add_question(self.section.id, Question.Type.NUMBER, revision)

        services.reorder_question(third.id, revision, self.section.id, 0)

        first.identity.refresh_from_db()
        second.identity.refresh_from_db()
        third.identity.refresh_from_db()
        self.assertEqual(
            (third.identity.order, first.identity.order, second.identity.order),
            (1, 2, 3),
        )

    def test_only_section_cannot_be_deleted(self):
        with self.assertRaisesMessage(
            ValidationError,
            'A survey must contain at least one section.',
        ):
            services.delete_section(self.section.id, self.version.revision)

    def test_autosave_rejects_stale_revision_and_accepts_current_revision(self):
        question, revision = services.add_question(
            self.section.id,
            Question.Type.SHORT_TEXT,
            self.version.revision,
        )
        self.client.force_login(self.user)
        url = reverse('question_update', args=[self.survey.id, question.id])
        data = {
            'type': Question.Type.SHORT_TEXT,
            'prompt': 'Updated prompt',
            'help_text': '',
            'min_length': 2,
            'max_length': 100,
        }

        stale_response = self.client.post(
            url,
            {**data, 'revision': revision - 1},
            HTTP_ACCEPT='application/json',
        )
        saved_response = self.client.post(
            url,
            {**data, 'revision': revision},
            HTTP_ACCEPT='application/json',
        )

        self.assertEqual(stale_response.status_code, 409)
        self.assertEqual(saved_response.status_code, 200)
        self.assertEqual(saved_response.json()['revision'], revision + 1)
        question.refresh_from_db()
        self.assertEqual(question.prompt, 'Updated prompt')
        self.assertEqual(question.config, {'min_length': 2, 'max_length': 100})
