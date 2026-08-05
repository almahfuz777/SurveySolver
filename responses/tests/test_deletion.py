from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from rewards.models import GuestRewardClaim, PointTransaction
from surveys.models import Question, Survey
from surveys.publication import publish_survey

from responses.deletion import permanently_delete_submission
from responses.models import ResponseAuditEvent, Submission


class ResponseManagementTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(email='management-owner@example.com')
        self.respondent = get_user_model().objects.create_user(email='management-user@example.com')
        self.survey = Survey.objects.create(
            owner=self.owner,
            title='Managed responses',
            summary='Response management fixtures.',
        )
        draft = self.survey.draft_version
        Question.objects.create(
            section=draft.sections.get(),
            type=Question.Type.SHORT_TEXT,
            prompt='Question',
        )
        self.version, _ = publish_survey(self.survey.id, self.owner, draft.revision)
        self.submission = Submission.objects.create(
            survey=self.survey,
            version=self.version,
            respondent=self.respondent,
            session_key_hash='d' * 64,
            presentation={'sections': []},
            eligibility_data={'targeted': False},
        )
        Submission.objects.filter(pk=self.submission.pk).update(
            status=Submission.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        self.submission.refresh_from_db()

    def test_deletion_preserves_ledger_and_audit_while_invalidating_claim(self):
        transaction = PointTransaction.objects.create(
            user=self.respondent,
            amount=10,
            reason=PointTransaction.Reason.SURVEY_COMPLETION,
            idempotency_key=f'survey-completion:{self.respondent.id}:{self.survey.id}',
            survey=self.survey,
            submission=self.submission,
            metadata={'submission_id': str(self.submission.id)},
        )
        claim = GuestRewardClaim.objects.create(
            submission=self.submission,
            survey=self.survey,
            points_snapshot=10,
            secret_hash='e' * 64,
            session_key_hash='f' * 64,
            expires_at=timezone.now() + timedelta(days=7),
        )

        permanently_delete_submission(self.submission.id, self.owner)

        self.assertFalse(Submission.objects.filter(pk=self.submission.id).exists())
        self.assertFalse(GuestRewardClaim.objects.filter(pk=claim.id).exists())
        transaction.refresh_from_db()
        self.assertIsNone(transaction.submission)
        event = ResponseAuditEvent.objects.get(action=ResponseAuditEvent.Action.DELETED)
        self.assertEqual(event.submission_id, self.submission.id)
