from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from surveys.models import Question, Survey
from surveys.publication import publish_survey

from responses.models import Answer, Submission
from responses.services import hash_session_key


class ResponseRuntimeTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            email='researcher@example.com',
            password='correct-horse-battery-staple',
        )
        self.survey = Survey.objects.create(
            owner=self.owner,
            title='Student wellbeing study',
            summary='A short study about student experiences.',
        )
        draft = self.survey.draft_version
        self.draft_question = Question.objects.create(
            section=draft.sections.get(),
            type=Question.Type.SHORT_TEXT,
            prompt='What helps you focus?',
            required=True,
            order=1,
        )
        self.published, _ = publish_survey(self.survey.id, self.owner, draft.revision)
        self.survey.refresh_from_db()
        self.question = Question.objects.get(section__version=self.published)

    def start(self):
        return self.client.post(reverse('respond_survey', args=[self.survey.slug]))

    def test_guest_response_is_bound_to_published_version_and_session(self):
        response = self.start()

        self.assertRedirects(response, reverse('response_form', args=[Submission.objects.get().id]))
        submission = Submission.objects.get()
        self.assertEqual(submission.version, self.published)
        self.assertIsNone(submission.respondent)
        self.assertEqual(
            submission.session_key_hash,
            hash_session_key(self.client.session.session_key),
        )
        self.assertNotEqual(submission.session_key_hash, self.client.session.session_key)

    def test_valid_guest_answers_are_normalized_and_submission_is_completed(self):
        self.start()
        submission = Submission.objects.get()

        response = self.client.post(
            reverse('response_form', args=[submission.id]),
            {f'q_{self.question.id}': '  Quiet study rooms  '},
        )

        self.assertRedirects(response, reverse('response_complete', args=[submission.id]))
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.COMPLETED)
        self.assertIsNotNone(submission.completed_at)
        self.assertEqual(submission.answers.get().value, 'Quiet study rooms')

    def test_invalid_answers_do_not_create_partial_results(self):
        self.start()
        submission = Submission.objects.get()

        response = self.client.post(reverse('response_form', args=[submission.id]), {})

        self.assertEqual(response.status_code, 422)
        self.assertContains(response, 'This question is required.', status_code=422)
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.IN_PROGRESS)
        self.assertFalse(Answer.objects.exists())

    def test_authenticated_start_records_platform_respondent(self):
        respondent = get_user_model().objects.create_user(
            email='respondent@example.com',
            password='correct-horse-battery-staple',
        )
        self.client.force_login(respondent)

        self.start()

        self.assertEqual(Submission.objects.get().respondent, respondent)

    def test_another_browser_cannot_open_guest_submission(self):
        self.start()
        submission = Submission.objects.get()

        response = self.client_class().get(reverse('response_form', args=[submission.id]))

        self.assertEqual(response.status_code, 403)

    def test_in_progress_response_uses_original_version_after_republication(self):
        self.start()
        submission = Submission.objects.get()
        next_draft = self.survey.draft_version
        Question.objects.create(
            section=next_draft.sections.get(),
            type=Question.Type.LONG_TEXT,
            prompt='What should universities improve?',
            order=2,
        )
        publish_survey(self.survey.id, self.owner, next_draft.revision)

        response = self.client.post(
            reverse('response_form', args=[submission.id]),
            {f'q_{self.question.id}': 'Library access'},
        )

        self.assertRedirects(response, reverse('response_complete', args=[submission.id]))
        submission.refresh_from_db()
        self.assertEqual(submission.version, self.published)
        self.assertEqual(submission.answers.count(), 1)

    def test_invitation_only_survey_is_not_publicly_startable(self):
        self.survey.visibility = Survey.Visibility.INVITATION_ONLY
        self.survey.save(update_fields=('visibility', 'updated_at'))

        response = self.client.get(reverse('respond_survey', args=[self.survey.slug]))

        self.assertEqual(response.status_code, 404)
