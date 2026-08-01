from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from surveys.models import Survey

from sharing.collaborator_invitations import create_collaborator_invitation
from sharing.models import CollaboratorInvitation, SurveyCollaborator


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class CollaboratorEmailInvitationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(email='email-owner@example.com')
        self.invited_user = User.objects.create_user(email='invited@example.com')
        self.other_user = User.objects.create_user(email='other@example.com')
        self.survey = Survey.objects.create(
            owner=self.owner,
            title='Emailed collaboration',
            summary='Email invitation fixtures.',
        )

    def test_owner_sends_email_without_persisting_raw_token(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('send_collaborator_invitation', args=[self.survey.id]),
            {'email': 'INVITED@example.com', 'role': SurveyCollaborator.Role.EDITOR},
        )

        self.assertRedirects(response, reverse('sharing_settings', args=[self.survey.id]))
        invitation = CollaboratorInvitation.objects.get()
        self.assertEqual(invitation.email, 'invited@example.com')
        self.assertEqual(invitation.delivery_status, CollaboratorInvitation.DeliveryStatus.SENT)
        self.assertIsNotNone(invitation.sent_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['invited@example.com'])
        self.assertIn(str(invitation.id), mail.outbox[0].body)
        self.assertNotIn(invitation.token_hash, mail.outbox[0].body)

    def test_acceptance_requires_matching_authenticated_email(self):
        invitation, token = create_collaborator_invitation(
            self.survey.id,
            self.owner,
            self.invited_user.email,
            SurveyCollaborator.Role.VIEWER,
        )
        url = reverse('accept_collaborator_invitation', args=[invitation.id, token])

        anonymous = self.client.get(url)
        self.assertRedirects(anonymous, f"{reverse('account_login')}?next={url}")
        self.client.force_login(self.other_user)
        mismatch = self.client.get(url)
        self.assertEqual(mismatch.status_code, 403)
        self.assertFalse(SurveyCollaborator.objects.exists())
        self.client.logout()
        self.client.force_login(self.invited_user)

        accepted = self.client.post(url)

        self.assertRedirects(accepted, reverse('survey_detail', args=[self.survey.id]), target_status_code=302)
        membership = SurveyCollaborator.objects.get(user=self.invited_user)
        self.assertEqual(membership.role, SurveyCollaborator.Role.VIEWER)
        invitation.refresh_from_db()
        self.assertEqual(invitation.accepted_by, self.invited_user)
        self.assertIsNotNone(invitation.accepted_at)

    def test_new_invitation_revokes_previous_active_invitation(self):
        first, _ = create_collaborator_invitation(
            self.survey.id,
            self.owner,
            self.invited_user.email,
            SurveyCollaborator.Role.VIEWER,
        )

        second, _ = create_collaborator_invitation(
            self.survey.id,
            self.owner,
            self.invited_user.email.upper(),
            SurveyCollaborator.Role.EDITOR,
        )

        first.refresh_from_db()
        self.assertIsNotNone(first.revoked_at)
        self.assertIsNone(second.revoked_at)

    def test_expired_or_revoked_invitation_is_unavailable(self):
        invitation, token = create_collaborator_invitation(
            self.survey.id,
            self.owner,
            self.invited_user.email,
            SurveyCollaborator.Role.VIEWER,
        )
        self.client.force_login(self.invited_user)
        url = reverse('accept_collaborator_invitation', args=[invitation.id, token])
        CollaboratorInvitation.objects.filter(pk=invitation.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        expired = self.client.get(url)

        self.assertEqual(expired.status_code, 410)
        self.assertFalse(SurveyCollaborator.objects.exists())

    def test_non_owner_cannot_send_or_revoke_invitations(self):
        invitation, _ = create_collaborator_invitation(
            self.survey.id,
            self.owner,
            self.invited_user.email,
            SurveyCollaborator.Role.VIEWER,
        )
        self.client.force_login(self.other_user)

        send = self.client.post(
            reverse('send_collaborator_invitation', args=[self.survey.id]),
            {'email': 'new@example.com', 'role': SurveyCollaborator.Role.VIEWER},
        )
        revoke = self.client.post(
            reverse(
                'revoke_collaborator_invitation',
                args=[self.survey.id, invitation.id],
            ),
        )

        self.assertEqual(send.status_code, 404)
        self.assertEqual(revoke.status_code, 404)
