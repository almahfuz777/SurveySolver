from datetime import timedelta

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from responses.models import Submission
from sharing.models import SurveyCollaborator
from surveys.models import Question, Survey
from surveys.publication import publish_survey

from rewards.claims import CLAIM_SECRET_SESSION_KEY, PENDING_CLAIM_SESSION_KEY
from rewards.models import BadgeAward, GuestRewardClaim, PointTransaction


class GuestRewardClaimTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(email='claim-owner@example.com')
        self.survey = Survey.objects.create(
            owner=self.owner,
            title='Reward claim study',
            summary='A study with a completion reward.',
        )
        draft = self.survey.draft_version
        Question.objects.create(
            section=draft.sections.get(),
            type=Question.Type.SHORT_TEXT,
            prompt='Share one idea',
            required=True,
            order=1,
        )
        self.version, _ = publish_survey(self.survey.id, self.owner, draft.revision)
        self.survey.refresh_from_db()
        self.question = self.version.sections.get().questions.get()

    def complete_guest_response(self):
        self.client.post(reverse('respond_survey', args=[self.survey.slug]))
        submission = Submission.objects.get()
        response = self.client.post(
            reverse('response_form', args=[submission.id]),
            {f'q_{self.question.id}': 'A thoughtful answer'},
        )
        self.assertRedirects(response, reverse('response_complete', args=[submission.id]))
        return submission

    def test_guest_completion_creates_hashed_seven_day_claim(self):
        submission = self.complete_guest_response()

        claim = GuestRewardClaim.objects.get(submission=submission)
        secret = self.client.session[CLAIM_SECRET_SESSION_KEY][str(claim.id)]
        self.assertEqual(claim.points_snapshot, 10)
        self.assertNotEqual(claim.secret_hash, secret)
        self.assertEqual(len(claim.secret_hash), 64)
        self.assertAlmostEqual(
            claim.expires_at,
            claim.created_at + timedelta(days=7),
            delta=timedelta(seconds=2),
        )
        completion = self.client.get(reverse('response_complete', args=[submission.id]))
        self.assertContains(completion, 'Create an account to claim 10 points')

    def test_claim_cta_stores_pending_claim_before_signup(self):
        self.complete_guest_response()
        claim = GuestRewardClaim.objects.get()
        secret = self.client.session[CLAIM_SECRET_SESSION_KEY][str(claim.id)]

        response = self.client.post(
            reverse('prepare_reward_claim', args=[claim.id]),
            {'claim_secret': secret},
        )

        self.assertRedirects(response, reverse('account_signup'))
        self.assertEqual(
            self.client.session[PENDING_CLAIM_SESSION_KEY],
            {
                'claim_id': str(claim.id),
                'secret': secret,
                'session_key_hash': claim.session_key_hash,
            },
        )

    def test_existing_user_path_preserves_claim_before_login(self):
        self.complete_guest_response()
        claim = GuestRewardClaim.objects.get()
        secret = self.client.session[CLAIM_SECRET_SESSION_KEY][str(claim.id)]

        response = self.client.post(
            reverse('prepare_reward_claim', args=[claim.id]),
            {'claim_secret': secret, 'destination': 'login'},
        )

        self.assertRedirects(response, reverse('account_login'))
        self.assertIn(PENDING_CLAIM_SESSION_KEY, self.client.session)

    def test_claim_cannot_be_moved_to_another_browser(self):
        self.complete_guest_response()
        claim = GuestRewardClaim.objects.get()
        secret = self.client.session[CLAIM_SECRET_SESSION_KEY][str(claim.id)]
        other_browser = self.client_class()

        response = other_browser.post(
            reverse('prepare_reward_claim', args=[claim.id]),
            {'claim_secret': secret},
        )

        self.assertRedirects(
            response,
            reverse('response_complete', args=[claim.submission_id]),
            fetch_redirect_response=False,
        )
        self.assertNotIn(PENDING_CLAIM_SESSION_KEY, other_browser.session)

    def test_expired_claim_cannot_be_prepared(self):
        self.complete_guest_response()
        claim = GuestRewardClaim.objects.get()
        secret = self.client.session[CLAIM_SECRET_SESSION_KEY][str(claim.id)]
        GuestRewardClaim.objects.filter(pk=claim.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        self.client.post(
            reverse('prepare_reward_claim', args=[claim.id]),
            {'claim_secret': secret},
        )

        self.assertNotIn(PENDING_CLAIM_SESSION_KEY, self.client.session)

    def test_authenticated_completion_does_not_create_guest_claim(self):
        respondent = get_user_model().objects.create_user(email='signed-in@example.com')
        self.client.force_login(respondent)
        self.client.post(reverse('respond_survey', args=[self.survey.slug]))
        submission = Submission.objects.get()

        self.client.post(
            reverse('response_form', args=[submission.id]),
            {f'q_{self.question.id}': 'Signed-in answer'},
        )

        self.assertFalse(GuestRewardClaim.objects.exists())
        transaction = PointTransaction.objects.get(user=respondent)
        self.assertEqual(transaction.amount, 10)
        self.assertEqual(transaction.survey, self.survey)
        self.assertEqual(transaction.submission, submission)
        self.assertEqual(
            BadgeAward.objects.get(user=respondent).badge.slug,
            'first-response',
        )

    def test_verified_login_consumes_claim_without_reidentifying_answers(self):
        submission = self.complete_guest_response()
        claim = GuestRewardClaim.objects.get()
        secret = self.client.session[CLAIM_SECRET_SESSION_KEY][str(claim.id)]
        self.client.post(
            reverse('prepare_reward_claim', args=[claim.id]),
            {'claim_secret': secret, 'destination': 'login'},
        )
        user = get_user_model().objects.create_user(
            email='claimant@example.com',
            password='correct-horse-battery-staple',
        )
        EmailAddress.objects.create(
            user=user,
            email=user.email,
            primary=True,
            verified=True,
        )

        response = self.client.post(
            reverse('account_login'),
            {'login': user.email, 'password': 'correct-horse-battery-staple'},
        )

        self.assertRedirects(response, reverse('dashboard'))
        claim.refresh_from_db()
        submission.refresh_from_db()
        self.assertEqual(claim.claimed_by, user)
        self.assertIsNotNone(claim.claimed_at)
        self.assertEqual(PointTransaction.objects.get(user=user).amount, 10)
        self.assertIsNone(submission.respondent)
        self.assertNotIn(PENDING_CLAIM_SESSION_KEY, self.client.session)

    def test_survey_owner_never_receives_completion_points(self):
        self.client.force_login(self.owner)
        self.client.post(reverse('respond_survey', args=[self.survey.slug]))
        submission = Submission.objects.get()

        self.client.post(
            reverse('response_form', args=[submission.id]),
            {f'q_{self.question.id}': 'Owner test response'},
        )

        self.assertFalse(
            PointTransaction.objects.filter(
                user=self.owner,
                reason=PointTransaction.Reason.SURVEY_COMPLETION,
            ).exists()
        )

    def test_deleting_response_invalidates_unclaimed_guest_claim(self):
        submission = self.complete_guest_response()
        claim_id = GuestRewardClaim.objects.get(submission=submission).id
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('creator_response_delete', args=[self.survey.id, submission.id]),
            {'confirmation': 'DELETE'},
        )

        self.assertRedirects(response, reverse('creator_response_list', args=[self.survey.id]))
        self.assertFalse(GuestRewardClaim.objects.filter(pk=claim_id).exists())

    def test_collaborator_never_receives_completion_points(self):
        collaborator = get_user_model().objects.create_user(email='collaborator@example.com')
        SurveyCollaborator.objects.create(
            survey=self.survey,
            user=collaborator,
            role=SurveyCollaborator.Role.VIEWER,
            added_by=self.owner,
        )
        self.client.force_login(collaborator)
        self.client.post(reverse('respond_survey', args=[self.survey.slug]))
        submission = Submission.objects.get()

        self.client.post(
            reverse('response_form', args=[submission.id]),
            {f'q_{self.question.id}': 'Collaborator test response'},
        )

        self.assertFalse(
            PointTransaction.objects.filter(
                user=collaborator,
                reason=PointTransaction.Reason.SURVEY_COMPLETION,
            ).exists()
        )
