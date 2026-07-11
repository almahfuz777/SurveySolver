from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from responses.models import Submission
from surveys.models import Question, Survey
from surveys.publication import publish_survey

from sharing.models import RespondentInvitation
from sharing.respondent_invitations import (
    create_respondent_invitation,
    revoke_respondent_invitation,
)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class RespondentInvitationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(email='respondent-owner@example.com')
        self.other_user = User.objects.create_user(email='other@example.com')
        self.survey = Survey.objects.create(
            owner=self.owner,
            title='Private student study',
            summary='Invitation-only response fixtures.',
            visibility=Survey.Visibility.INVITATION_ONLY,
        )
        draft = self.survey.draft_version
        Question.objects.create(
            section=draft.sections.get(),
            type=Question.Type.SHORT_TEXT,
            prompt='What supports your learning?',
            required=True,
            order=1,
        )
        self.published, _ = publish_survey(
            self.survey.id,
            self.owner,
            draft.revision,
        )
        self.survey.refresh_from_db()

    def test_owner_sends_single_use_email_without_persisting_raw_token(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('send_respondent_invitation', args=[self.survey.id]),
            {'email': 'PARTICIPANT@example.com'},
        )

        self.assertRedirects(response, reverse('sharing_settings', args=[self.survey.id]))
        invitation = RespondentInvitation.objects.get()
        self.assertEqual(invitation.email, 'participant@example.com')
        self.assertEqual(invitation.delivery_status, RespondentInvitation.DeliveryStatus.SENT)
        self.assertEqual(mail.outbox[0].to, ['participant@example.com'])
        self.assertIn(str(invitation.id), mail.outbox[0].body)
        self.assertNotIn(invitation.token_hash, mail.outbox[0].body)

    def test_guest_invitation_unlocks_survey_and_binds_one_anonymous_response(self):
        invitation, token = create_respondent_invitation(
            self.survey.id,
            self.owner,
            'guest@example.com',
        )

        opened = self.client.get(
            reverse('open_respondent_invitation', args=[invitation.id, token]),
        )
        self.assertRedirects(opened, reverse('respond_survey', args=[self.survey.slug]))
        landing = self.client.get(reverse('respond_survey', args=[self.survey.slug]))
        self.assertEqual(landing.status_code, 200)

        started = self.client.post(reverse('respond_survey', args=[self.survey.slug]))

        submission = Submission.objects.get()
        self.assertRedirects(started, reverse('response_form', args=[submission.id]))
        self.assertEqual(submission.source, Submission.Source.INVITATION)
        self.assertEqual(submission.identity_data, {})
        self.assertIsNone(submission.respondent)
        invitation.refresh_from_db()
        self.assertEqual(invitation.bound_submission_id, submission.id)
        self.assertIsNotNone(invitation.consumed_at)

    def test_forwarded_grant_cannot_start_second_response(self):
        invitation, token = create_respondent_invitation(
            self.survey.id,
            self.owner,
            'guest@example.com',
        )
        url = reverse('open_respondent_invitation', args=[invitation.id, token])
        other_browser = self.client_class()
        self.client.get(url)
        other_browser.get(url)
        self.client.post(reverse('respond_survey', args=[self.survey.slug]))

        blocked = other_browser.post(reverse('respond_survey', args=[self.survey.slug]))

        self.assertEqual(blocked.status_code, 404)
        self.assertEqual(Submission.objects.count(), 1)
        self.assertEqual(self.client_class().get(url).status_code, 410)

    def test_same_browser_can_return_to_bound_response(self):
        invitation, token = create_respondent_invitation(
            self.survey.id,
            self.owner,
            'guest@example.com',
        )
        self.client.get(reverse('open_respondent_invitation', args=[invitation.id, token]))
        self.client.post(reverse('respond_survey', args=[self.survey.slug]))
        submission = Submission.objects.get()

        resumed = self.client.post(reverse('respond_survey', args=[self.survey.slug]))

        self.assertRedirects(resumed, reverse('response_form', args=[submission.id]))
        self.assertEqual(Submission.objects.count(), 1)

    def test_expired_revoked_and_tampered_invitations_are_unavailable(self):
        invitation, token = create_respondent_invitation(
            self.survey.id,
            self.owner,
            'guest@example.com',
        )
        url = reverse('open_respondent_invitation', args=[invitation.id, token])
        self.assertEqual(
            self.client.get(
                reverse('open_respondent_invitation', args=[invitation.id, 'tampered'])
            ).status_code,
            410,
        )
        RespondentInvitation.objects.filter(pk=invitation.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        self.assertEqual(self.client.get(url).status_code, 410)
        revoked, revoked_token = create_respondent_invitation(
            self.survey.id,
            self.owner,
            'revoked@example.com',
        )
        revoke_respondent_invitation(revoked.id, self.owner)
        self.assertEqual(
            self.client.get(
                reverse('open_respondent_invitation', args=[revoked.id, revoked_token])
            ).status_code,
            410,
        )

    def test_non_owner_cannot_send_or_revoke_respondent_invitations(self):
        invitation, _ = create_respondent_invitation(
            self.survey.id,
            self.owner,
            'guest@example.com',
        )
        self.client.force_login(self.other_user)

        send = self.client.post(
            reverse('send_respondent_invitation', args=[self.survey.id]),
            {'email': 'new@example.com'},
        )
        revoke = self.client.post(
            reverse('revoke_respondent_invitation', args=[self.survey.id, invitation.id]),
        )

        self.assertEqual(send.status_code, 404)
        self.assertEqual(revoke.status_code, 404)

    def test_draft_survey_cannot_send_respondent_invitations(self):
        draft_survey = Survey.objects.create(
            owner=self.owner,
            title='Draft study',
            summary='Not ready for respondents.',
        )

        with self.assertRaisesMessage(ValidationError, 'Publish this survey'):
            create_respondent_invitation(
                draft_survey.id,
                self.owner,
                'guest@example.com',
            )
