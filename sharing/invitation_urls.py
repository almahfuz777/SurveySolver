"""Tokenised links an invited respondent opens to reach a private survey."""
from django.urls import path

from . import views


urlpatterns = [
    path(
        'respond/<uuid:invitation_id>/<str:token>/',
        views.open_respondent_invitation,
        name='open_respondent_invitation',
    ),
]
