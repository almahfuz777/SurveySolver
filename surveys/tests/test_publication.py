from django.contrib.auth import get_user_model
from django.test import TestCase

from surveys import services
from surveys.models import Question, Survey, SurveyVersion
from surveys.publication import PublicationError, publish_survey


class PublicationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email='publisher@example.com')
        self.survey = Survey.objects.create(owner=self.user, title='Publishable study', summary='Safe version snapshots.')

    def test_empty_questionnaire_cannot_publish(self):
        with self.assertRaises(PublicationError) as error:
            publish_survey(self.survey.id, self.user, self.survey.draft_version.revision)
        self.assertIn('Add at least one question.', error.exception.errors)

    def test_publish_freezes_snapshot_and_creates_next_draft(self):
        draft = self.survey.draft_version
        section = draft.sections.get()
        question, revision = services.add_question(section.id, Question.Type.SHORT_TEXT, draft.revision)
        question.prompt = 'Original published wording'
        question.save()

        published, next_draft = publish_survey(self.survey.id, self.user, revision)

        self.survey.refresh_from_db()
        self.assertEqual(self.survey.status, Survey.Status.PUBLISHED)
        self.assertEqual(published.status, SurveyVersion.Status.PUBLISHED)
        self.assertEqual(next_draft.number, 2)
        self.assertEqual(next_draft.status, SurveyVersion.Status.DRAFT)
        self.assertEqual(next_draft.sections.get().questions.get().prompt, 'Original published wording')

        cloned_question = next_draft.sections.get().questions.get()
        cloned_question.prompt = 'Edited next-version wording'
        cloned_question.save()
        published_question = published.sections.get().questions.get()
        self.assertEqual(published_question.prompt, 'Original published wording')

    def test_next_publication_retires_previous_version(self):
        first_draft = self.survey.draft_version
        _, revision = services.add_question(first_draft.sections.get().id, Question.Type.DATE, first_draft.revision)
        first_published, second_draft = publish_survey(self.survey.id, self.user, revision)
        _, revision = services.add_question(second_draft.sections.get().id, Question.Type.NUMBER, second_draft.revision)

        second_published, third_draft = publish_survey(self.survey.id, self.user, revision)

        first_published.refresh_from_db()
        self.assertEqual(first_published.status, SurveyVersion.Status.RETIRED)
        self.assertEqual(second_published.status, SurveyVersion.Status.PUBLISHED)
        self.assertEqual(third_draft.number, 3)
