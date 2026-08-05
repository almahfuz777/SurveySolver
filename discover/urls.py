"""The public survey catalogue.

Kept at the site root rather than under /surveys/ because it is the browsing entry point for respondents, not a management page.
"""
from django.urls import path

from . import views


urlpatterns = [
    path('', views.discover, name='discover'),
]
