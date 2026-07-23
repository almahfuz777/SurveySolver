from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from responses.models import Answer, Submission
from responses.services import build_presentation, hash_session_key
from sharing.models import SurveyCollaborator
from surveys.models import Question, QuestionChoice, Survey
from surveys.publication import publish_survey


class SurveyAnalyticsDashboardTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(email='analytics-owner@example.com')
        self.viewer = User.objects.create_user(email='analytics-viewer@example.com')
        self.outsider = User.objects.create_user(email='analytics-outsider@example.com')
        self.survey = Survey.objects.create(
            owner=self.owner,
            title='Analytics study',
            summary='Version-aware analytics fixtures.',
        )
        draft = self.survey.draft_version
        question = Question.objects.create(
            section=draft.sections.get(),
            type=Question.Type.SINGLE_CHOICE,
            prompt='Preferred study setting?',
            required=True,
            order=1,
        )
        QuestionChoice.objects.create(question=question, label='Library', order=1)
        QuestionChoice.objects.create(question=question, label='Home', order=2)
        self.version, _ = publish_survey(self.survey.id, self.owner, draft.revision)
        self.survey.refresh_from_db()
        self.question = self.version.sections.get().questions.get()
        self.library = self.question.choices.get(label='Library')
        SurveyCollaborator.objects.create(
            survey=self.survey,
            user=self.viewer,
            role=SurveyCollaborator.Role.VIEWER,
            added_by=self.owner,
        )
        self.counter = 0

    def create_submission(
        self,
        *,
        completed=True,
        excluded=False,
        country='BD',
        question=None,
        choice=None,
    ):
        self.counter += 1
        question = question or self.question
        choice = choice or self.library
        submission = Submission.objects.create(
            survey=self.survey,
            version=question.section.version,
            session_key_hash=hash_session_key(f'analytics-session-{self.counter}'),
            presentation=build_presentation(question.section.version),
            eligibility_data={'targeted': True, 'country': country},
            eligibility_checked_at=timezone.now(),
        )
        if completed:
            Answer.objects.create(
                submission=submission,
                question=question,
                value={'choice_id': str(choice.id), 'label': choice.label},
            )
            completed_at = timezone.now()
            Submission.objects.filter(pk=submission.pk).update(
                status=Submission.Status.COMPLETED,
                started_at=completed_at - timedelta(seconds=90),
                completed_at=completed_at,
                is_excluded=excluded,
            )
        return Submission.objects.get(pk=submission.pk)

    def test_owner_and_viewer_can_access_but_outsider_cannot(self):
        url = reverse('survey_analytics', args=[self.survey.id])
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_metrics_question_distribution_and_exclusions(self):
        self.create_submission()
        self.create_submission(completed=False)
        self.create_submission(excluded=True)
        self.client.force_login(self.owner)

        response = self.client.get(reverse('survey_analytics', args=[self.survey.id]))

        self.assertContains(response, '<strong>2</strong>', html=True)
        self.assertContains(response, '50.0% completion rate')
        self.assertContains(response, 'Preferred study setting?')
        self.assertContains(response, 'Library')
        self.assertContains(response, '1m 30s')

    def test_version_filter_keeps_question_summaries_separate(self):
        self.create_submission()
        second_draft = self.survey.draft_version
        second_version, _ = publish_survey(
            self.survey.id,
            self.owner,
            second_draft.revision,
        )
        second_question = second_version.sections.get().questions.get()
        second_choice = second_question.choices.get(label='Home')
        self.create_submission(question=second_question, choice=second_choice)
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse('survey_analytics', args=[self.survey.id]),
            {'version': second_version.id},
        )

        self.assertContains(response, 'Version 2')
        self.assertContains(response, 'Home')
        self.assertNotContains(response, '>Library<')

    def test_demographic_groups_smaller_than_five_are_suppressed(self):
        for _ in range(4):
            self.create_submission(country='BD')
        self.create_submission(country='US')
        self.client.force_login(self.owner)
        url = reverse('survey_analytics', args=[self.survey.id])

        suppressed = self.client.get(url)

        self.assertContains(suppressed, 'small groups are hidden')
        self.assertNotContains(suppressed, 'Bangladesh')
        self.assertNotContains(suppressed, 'United States')

        self.create_submission(country='BD')
        visible = self.client.get(url)
        self.assertContains(visible, 'Bangladesh')
        self.assertNotContains(visible, 'United States')
