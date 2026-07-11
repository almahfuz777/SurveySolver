import csv
import io
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sharing.models import SurveyCollaborator
from surveys.models import Question, Survey
from surveys.publication import publish_survey

from responses.models import Submission


class ResponseExportTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(email='export-owner@example.com')
        self.respondent = User.objects.create_user(email='private-export-user@example.com')
        self.viewer = User.objects.create_user(email='export-viewer@example.com')
        self.outsider = User.objects.create_user(email='export-outsider@example.com')
        self.survey = Survey.objects.create(
            owner=self.owner,
            title='Unicode export study',
            summary='Filtered export fixtures.',
        )
        draft = self.survey.draft_version
        Question.objects.create(
            section=draft.sections.get(),
            type=Question.Type.LONG_TEXT,
            prompt='Describe your experience',
            required=True,
            order=1,
        )
        self.version, _ = publish_survey(self.survey.id, self.owner, draft.revision)
        self.survey.refresh_from_db()
        self.question = self.version.sections.get().questions.get()
        SurveyCollaborator.objects.create(
            survey=self.survey,
            user=self.viewer,
            role=SurveyCollaborator.Role.VIEWER,
            added_by=self.owner,
        )

    def complete_response(self):
        browser = self.client_class()
        browser.force_login(self.respondent)
        browser.post(reverse('respond_survey', args=[self.survey.slug]))
        submission = Submission.objects.get()
        browser.post(
            reverse('response_form', args=[submission.id]),
            {f'q_{self.question.id}': '=1+1\nবাংলা response'},
        )
        submission.refresh_from_db()
        return submission

    def body(self, response):
        return b''.join(response.streaming_content)

    def test_csv_exports_filtered_unicode_multiline_answers(self):
        completed = self.complete_response()
        Submission.objects.create(
            survey=self.survey,
            version=self.version,
            session_key_hash='f' * 64,
            presentation={'sections': []},
        )
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse('response_export_csv', args=[self.survey.id]),
            {'completion': Submission.Status.COMPLETED, 'exclusion': 'included'},
        )

        rows = list(
            csv.reader(io.StringIO(self.body(response).decode('utf-8-sig')))
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(rows), 2)
        self.assertIn(str(completed.id), rows[1])
        self.assertIn("'=1+1\nবাংলা response", rows[1])
        self.assertNotIn(self.respondent.email, rows[1])

    def test_json_preserves_structured_records_without_platform_identity(self):
        submission = self.complete_response()
        self.client.force_login(self.owner)

        response = self.client.get(reverse('response_export_json', args=[self.survey.id]))
        payload = json.loads(self.body(response))

        self.assertEqual(payload['survey']['id'], str(self.survey.id))
        self.assertEqual(payload['responses'][0]['response_id'], str(submission.id))
        self.assertEqual(
            payload['responses'][0]['answers'][0]['value'],
            '=1+1\nবাংলা response',
        )
        self.assertIsNone(payload['responses'][0]['identity_email'])
        self.assertNotIn(self.respondent.email, self.body(response).decode())

    def test_viewer_can_export_but_outsider_cannot(self):
        self.complete_response()
        url = reverse('response_export_json', args=[self.survey.id])
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_invalid_filters_return_bad_request(self):
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse('response_export_csv', args=[self.survey.id]),
            {'date_from': '2026-02-02', 'date_to': '2026-01-01'},
        )

        self.assertEqual(response.status_code, 400)
