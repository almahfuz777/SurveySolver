from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from surveys.models import Question, QuestionChoice, Section, Survey, SurveyVersion


class QuestionnaireModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email='builder@example.com')
        self.survey = Survey.objects.create(
            owner=self.user,
            title='Versioned research',
            summary='Testing versioned questionnaire models.',
        )
        self.version = self.survey.draft_version
        self.section = self.version.sections.get()

    def test_new_survey_gets_initial_draft_and_section(self):
        self.assertEqual(self.version.number, 1)
        self.assertEqual(self.version.status, SurveyVersion.Status.DRAFT)
        self.assertEqual(self.version.created_by, self.user)
        self.assertEqual(self.section.title, 'Section 1')
        self.assertEqual(self.section.order, 1)

    def test_question_and_choices_preserve_explicit_order(self):
        question = Question.objects.create(
            section=self.section,
            type=Question.Type.SINGLE_CHOICE,
            prompt='Which option fits best?',
            required=True,
            order=1,
        )
        second = QuestionChoice.objects.create(question=question, label='Second', order=2)
        first = QuestionChoice.objects.create(question=question, label='First', order=1)

        self.assertTrue(question.accepts_choices)
        self.assertEqual(list(question.choices.all()), [first, second])

    def test_version_allows_only_one_draft_per_survey(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            SurveyVersion.objects.create(
                survey=self.survey,
                number=2,
                created_by=self.user,
            )

    def test_section_order_is_unique_within_version(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Section.objects.create(version=self.version, title='Duplicate', order=1)

    def test_published_version_and_questions_are_immutable(self):
        question = Question.objects.create(
            section=self.section,
            type=Question.Type.SHORT_TEXT,
            prompt='Original wording',
            order=1,
        )
        self.version.status = SurveyVersion.Status.PUBLISHED
        self.version.save()

        self.version.revision += 1
        with self.assertRaisesMessage(ValidationError, 'Published survey versions are immutable.'):
            self.version.save()

        question.prompt = 'Changed wording'
        with self.assertRaisesMessage(ValidationError, 'Published survey versions are immutable.'):
            question.save()
