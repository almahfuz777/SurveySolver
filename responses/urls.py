"""Filling in a response, from the form through to completion."""
from django.urls import path

from . import views


urlpatterns = [
    path('<uuid:submission_id>/', views.submission_form, name='response_form'),
    path('<uuid:submission_id>/discard/', views.submission_discard, name='response_discard'),
    path('<uuid:submission_id>/complete/', views.submission_complete, name='response_complete'),
]
