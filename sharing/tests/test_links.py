from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from surveys.models import Survey

from sharing.models import CollaborationLink, SurveyCollaborator
from sharing.services import accept_collaboration_link, create_collaboration_link


class CollaborationLinkTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(email='link-owner@example.com')
        self.member = User.objects.create_user(email='link-member@example.com')
        self.editor = User.objects.create_user(email='existing-editor@example.com')
        self.survey = Survey.objects.create(
            owner=self.owner,
            title='Link sharing study',
            summary='Collaboration link fixtures.',
        )

    def create_link(self, role=SurveyCollaborator.Role.VIEWER):
        return create_collaboration_link(self.survey.id, self.owner, role)

    def test_created_link_stores_only_hash_and_is_shown_once(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('sharing_settings', args=[self.survey.id]),
            {'role': SurveyCollaborator.Role.EDITOR, 'lifetime_days': '7'},
            follow=True,
        )

        link = CollaborationLink.objects.get()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Copy this link now')
        self.assertContains(response, f'/collaborate/{link.id}/')
        self.assertNotContains(response, link.token_hash)
        next_page = self.client.get(reverse('sharing_settings', args=[self.survey.id]))
        self.assertNotContains(next_page, 'Copy this link now')

    def test_acceptance_requires_sign_in_and_explicit_confirmation(self):
        link, token = self.create_link()
        accept_url = reverse('accept_collaboration_link', args=[link.id, token])

        anonymous = self.client.get(accept_url)

        self.assertRedirects(
            anonymous,
            f"{reverse('account_login')}?next={accept_url}",
        )
        self.client.force_login(self.member)
        confirmation = self.client.get(accept_url)
        self.assertEqual(confirmation.status_code, 200)
        self.assertFalse(SurveyCollaborator.objects.exists())

        accepted = self.client.post(accept_url)

        self.assertRedirects(accepted, reverse('survey_detail', args=[self.survey.id]))
        membership = SurveyCollaborator.objects.get(user=self.member)
        self.assertEqual(membership.role, SurveyCollaborator.Role.VIEWER)
        link.refresh_from_db()
        self.assertEqual(link.accepted_count, 1)
        self.assertIsNotNone(link.last_accepted_at)

    def test_revoked_expired_and_tampered_links_are_rejected(self):
        link, token = self.create_link()
        self.client.force_login(self.member)
        wrong = self.client.get(reverse('accept_collaboration_link', args=[link.id, 'wrong-token']))
        self.assertEqual(wrong.status_code, 410)

        link.revoked_at = timezone.now()
        link.save(update_fields=('revoked_at',))
        revoked = self.client.get(reverse('accept_collaboration_link', args=[link.id, token]))
        self.assertEqual(revoked.status_code, 410)
        link.revoked_at = None
        link.expires_at = timezone.now() - timedelta(seconds=1)
        link.save(update_fields=('revoked_at', 'expires_at'))
        expired = self.client.get(reverse('accept_collaboration_link', args=[link.id, token]))
        self.assertEqual(expired.status_code, 410)
        self.assertFalse(SurveyCollaborator.objects.exists())

    def test_viewer_link_never_downgrades_existing_editor(self):
        SurveyCollaborator.objects.create(
            survey=self.survey,
            user=self.editor,
            role=SurveyCollaborator.Role.EDITOR,
            added_by=self.owner,
        )
        link, token = self.create_link(SurveyCollaborator.Role.VIEWER)

        membership, created = accept_collaboration_link(link.id, token, self.editor)

        self.assertFalse(created)
        self.assertEqual(membership.role, SurveyCollaborator.Role.EDITOR)

    def test_only_owner_can_manage_links_and_collaborators(self):
        membership = SurveyCollaborator.objects.create(
            survey=self.survey,
            user=self.member,
            role=SurveyCollaborator.Role.VIEWER,
            added_by=self.owner,
        )
        link, _ = self.create_link()
        self.client.force_login(self.member)

        self.assertEqual(
            self.client.get(reverse('sharing_settings', args=[self.survey.id])).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                reverse('revoke_collaboration_link', args=[self.survey.id, link.id]),
            ).status_code,
            404,
        )
        self.client.logout()
        self.client.force_login(self.owner)

        updated = self.client.post(
            reverse('manage_collaborator', args=[self.survey.id, membership.id]),
            {'action': 'update', 'role': SurveyCollaborator.Role.EDITOR},
        )
        self.assertRedirects(updated, reverse('sharing_settings', args=[self.survey.id]))
        membership.refresh_from_db()
        self.assertEqual(membership.role, SurveyCollaborator.Role.EDITOR)
        self.client.post(
            reverse('revoke_collaboration_link', args=[self.survey.id, link.id]),
        )
        link.refresh_from_db()
        self.assertIsNotNone(link.revoked_at)
