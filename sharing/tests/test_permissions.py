from django.contrib.auth import get_user_model
from django.test import TestCase

from surveys.models import Survey

from sharing.models import SurveyCollaborator
from sharing.permissions import EDIT_ROLES, VIEW_ROLES, accessible_surveys, role_for


class CollaborationPermissionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(email='sharing-owner@example.com')
        self.editor = User.objects.create_user(email='sharing-editor@example.com')
        self.viewer = User.objects.create_user(email='sharing-viewer@example.com')
        self.outsider = User.objects.create_user(email='sharing-outsider@example.com')
        self.survey = Survey.objects.create(
            owner=self.owner,
            title='Shared study',
            summary='Collaboration permission fixtures.',
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

    def test_roles_are_resolved_from_owner_and_memberships(self):
        self.assertEqual(role_for(self.owner, self.survey), 'owner')
        self.assertEqual(role_for(self.editor, self.survey), SurveyCollaborator.Role.EDITOR)
        self.assertEqual(role_for(self.viewer, self.survey), SurveyCollaborator.Role.VIEWER)
        self.assertIsNone(role_for(self.outsider, self.survey))

    def test_accessible_querysets_enforce_role_thresholds(self):
        self.assertTrue(accessible_surveys(self.owner, VIEW_ROLES).filter(pk=self.survey.pk).exists())
        self.assertTrue(accessible_surveys(self.editor, EDIT_ROLES).filter(pk=self.survey.pk).exists())
        self.assertFalse(accessible_surveys(self.viewer, EDIT_ROLES).filter(pk=self.survey.pk).exists())
        self.assertFalse(accessible_surveys(self.outsider, VIEW_ROLES).filter(pk=self.survey.pk).exists())
