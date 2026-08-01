"""Tokenised links an invited collaborator opens to gain access.

Public by necessity: the recipient is often signed out, or has no account yet.
"""
from django.urls import path

from . import views


urlpatterns = [
    path(
        '<uuid:link_id>/<str:token>/',
        views.accept_link,
        name='accept_collaboration_link',
    ),
    path(
        'invitation/<uuid:invitation_id>/<str:token>/',
        views.accept_invitation,
        name='accept_collaborator_invitation',
    ),
]
