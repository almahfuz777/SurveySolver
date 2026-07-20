from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

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

    def test_question_mutations_increment_version_revision(self):
        question, revision = services.add_question(
            self.section.id,
            Question.Type.SHORT_TEXT,
            self.version.revision,
        )

        self.assertEqual(revision, 2)
        self.assertEqual(question.order, 1)
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

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((second.order, first.order), (1, 2))

    def test_add_question_after_inserts_and_shifts_tail(self):
        first, revision = services.add_question(self.section.id, Question.Type.SHORT_TEXT, self.version.revision)
        second, revision = services.add_question(self.section.id, Question.Type.LONG_TEXT, revision)

        inserted, revision = services.add_question(
            self.section.id, Question.Type.NUMBER, revision, after_order=first.order
        )

        second.refresh_from_db()
        self.assertEqual(inserted.order, 2)
        self.assertEqual(second.order, 3)

    def test_duplicate_question_clones_choices_after_original(self):
        original, revision = services.add_question(self.section.id, Question.Type.SINGLE_CHOICE, self.version.revision)
        tail, revision = services.add_question(self.section.id, Question.Type.SHORT_TEXT, revision)

        clone, revision = services.duplicate_question(original.id, revision)

        tail.refresh_from_db()
        self.assertEqual(clone.order, original.order + 1)
        self.assertEqual(tail.order, 3)
        self.assertEqual(clone.type, original.type)
        self.assertEqual(
            list(clone.choices.order_by('order').values_list('label', flat=True)),
            list(original.choices.order_by('order').values_list('label', flat=True)),
        )
        self.assertNotEqual(clone.id, original.id)

    def test_reorder_question_moves_across_sections(self):
        other, revision = services.add_section(self.version.id, self.version.revision)
        first, revision = services.add_question(self.section.id, Question.Type.SHORT_TEXT, revision)
        second, revision = services.add_question(self.section.id, Question.Type.LONG_TEXT, revision)

        services.reorder_question(first.id, revision, other.id, 0)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.section_id, other.id)
        self.assertEqual(first.order, 1)
        self.assertEqual(second.order, 1)

    def test_reorder_question_within_section(self):
        first, revision = services.add_question(self.section.id, Question.Type.SHORT_TEXT, self.version.revision)
        second, revision = services.add_question(self.section.id, Question.Type.LONG_TEXT, revision)
        third, revision = services.add_question(self.section.id, Question.Type.NUMBER, revision)

        services.reorder_question(third.id, revision, self.section.id, 0)

        first.refresh_from_db()
        second.refresh_from_db()
        third.refresh_from_db()
        self.assertEqual((third.order, first.order, second.order), (1, 2, 3))

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
