from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from surveys.models import Question, Survey, SurveyVersion

from responses.models import Submission


class SubmissionModelTests(TestCase):
    def setUp(self):
        owner = get_user_model().objects.create_user(email='owner@example.com')
        self.survey = Survey.objects.create(
            owner=owner,
            title='Response records',
            summary='Response record fixtures.',
        )
        self.version = self.survey.draft_version
        Question.objects.create(
            section=self.version.sections.get(),
            type=Question.Type.SHORT_TEXT,
            prompt='Question',
            order=1,
        )

    def test_submission_version_must_belong_to_survey(self):
        other = Survey.objects.create(
            owner=self.survey.owner,
            title='Other survey',
            summary='Another survey.',
        )
        submission = Submission(
            survey=self.survey,
            version=other.draft_version,
            session_key_hash='a' * 64,
            presentation={'sections': []},
        )

        with self.assertRaisesMessage(ValidationError, 'must belong to the survey'):
            submission.save()

    def test_completed_submission_cannot_be_changed(self):
        submission = Submission.objects.create(
            survey=self.survey,
            version=self.version,
            session_key_hash='a' * 64,
            presentation={'sections': []},
        )
        Submission.objects.filter(pk=submission.pk).update(
            status=Submission.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        submission.refresh_from_db()
        submission.source = Submission.Source.DISCOVERY

        with self.assertRaisesMessage(ValidationError, 'immutable'):
            submission.save()

    def test_anonymous_submission_rejects_creator_visible_identity(self):
        submission = Submission(
            survey=self.survey,
            version=self.version,
            session_key_hash='a' * 64,
            presentation={'sections': []},
            identity_data={'name': 'Hidden respondent'},
            identity_consent_at=timezone.now(),
        )

        with self.assertRaisesMessage(ValidationError, 'cannot contain'):
            submission.save()
