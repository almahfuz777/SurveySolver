"""Managing who a survey is shared with.

Mounted under the /surveys/ prefix because these pages hang off a survey the user manages.
"""
from django.urls import path

from . import views


urlpatterns = [
    path(
        '<uuid:survey_id>/sharing/',
        views.sharing_settings,
        name='sharing_settings',
    ),
    path(
        '<uuid:survey_id>/sharing/links/<uuid:link_id>/revoke/',
        views.revoke_link,
        name='revoke_collaboration_link',
    ),
    path(
        '<uuid:survey_id>/sharing/invitations/send/',
        views.send_collaborator_invitation,
        name='send_collaborator_invitation',
    ),
    path(
        '<uuid:survey_id>/sharing/invitations/<uuid:invitation_id>/revoke/',
        views.revoke_invitation,
        name='revoke_collaborator_invitation',
    ),
    path(
        '<uuid:survey_id>/sharing/respondents/send/',
        views.send_respondent_invitation,
        name='send_respondent_invitation',
    ),
    path(
        '<uuid:survey_id>/sharing/respondents/<uuid:invitation_id>/revoke/',
        views.revoke_respondent_invite,
        name='revoke_respondent_invitation',
    ),
    path(
        '<uuid:survey_id>/sharing/collaborators/<uuid:collaborator_id>/',
        views.manage_collaborator,
        name='manage_collaborator',
    ),
]
