from django.urls import path

from . import views


urlpatterns = [
    path(
        'dashboard/surveys/<uuid:survey_id>/sharing/',
        views.sharing_settings,
        name='sharing_settings',
    ),
    path(
        'dashboard/surveys/<uuid:survey_id>/sharing/links/<uuid:link_id>/revoke/',
        views.revoke_link,
        name='revoke_collaboration_link',
    ),
    path(
        'dashboard/surveys/<uuid:survey_id>/sharing/invitations/send/',
        views.send_collaborator_invitation,
        name='send_collaborator_invitation',
    ),
    path(
        'dashboard/surveys/<uuid:survey_id>/sharing/invitations/<uuid:invitation_id>/revoke/',
        views.revoke_invitation,
        name='revoke_collaborator_invitation',
    ),
    path(
        'dashboard/surveys/<uuid:survey_id>/sharing/collaborators/<uuid:collaborator_id>/',
        views.manage_collaborator,
        name='manage_collaborator',
    ),
    path(
        'collaborate/<uuid:link_id>/<str:token>/',
        views.accept_link,
        name='accept_collaboration_link',
    ),
    path(
        'collaborate/invitation/<uuid:invitation_id>/<str:token>/',
        views.accept_invitation,
        name='accept_collaborator_invitation',
    ),
]
