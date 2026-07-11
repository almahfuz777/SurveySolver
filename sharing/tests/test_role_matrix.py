from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from responses.models import Submission
from surveys.models import Question, Survey

from sharing.models import SurveyCollaborator


class CollaborationRoleMatrixTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(email='matrix-owner@example.com')
        self.editor = User.objects.create_user(email='matrix-editor@example.com')
        self.viewer = User.objects.create_user(email='matrix-viewer@example.com')
        self.outsider = User.objects.create_user(email='matrix-outsider@example.com')
        self.survey = Survey.objects.create(
            owner=self.owner,
            title='Role matrix study',
            summary='Collaboration role matrix fixtures.',
        )
        draft = self.survey.draft_version
        Question.objects.create(
            section=draft.sections.get(),
            type=Question.Type.SHORT_TEXT,
            prompt='Question',
            order=1,
        )
        SurveyCollaborator.objects.create(
            survey=self.survey,
            user=self.editor,
            role=SurveyCollaborator.Role.EDITOR,
            added_by=self.owner,
        )
        SurveyCollaborator.objects.create(
            survey=self.survey,
            user=self.viewer,
            role=SurveyCollaborator.Role.VIEWER,
            added_by=self.owner,
        )

    def login(self, user):
        self.client.force_login(user)

    def test_editor_can_edit_publish_and_read_responses_but_not_archive(self):
        self.login(self.editor)

        self.assertEqual(self.client.get(reverse('survey_edit', args=[self.survey.id])).status_code, 200)
        self.assertEqual(self.client.get(reverse('survey_builder', args=[self.survey.id])).status_code, 200)
        published = self.client.post(
            reverse('survey_publish', args=[self.survey.id]),
            {'revision': self.survey.draft_version.revision},
        )
        self.assertRedirects(published, reverse('survey_detail', args=[self.survey.id]))
        self.assertEqual(
            self.client.get(reverse('creator_response_list', args=[self.survey.id])).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(reverse('survey_archive', args=[self.survey.id])).status_code,
            404,
        )

    def test_viewer_has_read_only_survey_and_response_access(self):
        self.login(self.viewer)

        self.assertEqual(self.client.get(reverse('survey_detail', args=[self.survey.id])).status_code, 200)
        self.assertEqual(self.client.get(reverse('survey_preview', args=[self.survey.id])).status_code, 200)
        self.assertEqual(
            self.client.get(reverse('creator_response_list', args=[self.survey.id])).status_code,
            200,
        )
        self.assertEqual(self.client.get(reverse('survey_edit', args=[self.survey.id])).status_code, 404)
        self.assertEqual(self.client.get(reverse('survey_builder', args=[self.survey.id])).status_code, 404)
        self.assertEqual(
            self.client.post(
                reverse('survey_publish', args=[self.survey.id]),
                {'revision': self.survey.draft_version.revision},
            ).status_code,
            404,
        )

    def test_only_owner_can_permanently_delete_response(self):
        submission = Submission.objects.create(
            survey=self.survey,
            version=self.survey.draft_version,
            session_key_hash='9' * 64,
            presentation={'sections': []},
        )
        Submission.objects.filter(pk=submission.pk).update(
            status=Submission.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        delete_url = reverse('creator_response_delete', args=[self.survey.id, submission.id])

        self.login(self.editor)
        self.assertEqual(self.client.get(delete_url).status_code, 404)
        self.client.logout()
        self.login(self.viewer)
        self.assertEqual(self.client.get(delete_url).status_code, 404)
        self.client.logout()
        self.login(self.owner)
        self.assertEqual(self.client.get(delete_url).status_code, 200)

    def test_outsider_cannot_discover_shared_dashboard_routes(self):
        self.login(self.outsider)

        self.assertEqual(self.client.get(reverse('survey_detail', args=[self.survey.id])).status_code, 404)
        self.assertEqual(
            self.client.get(reverse('creator_response_list', args=[self.survey.id])).status_code,
            404,
        )
