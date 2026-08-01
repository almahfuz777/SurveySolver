"""The public survey catalogue.

Kept at the site root rather than under /surveys/ because it is the browsing entry point for respondents, not a management page.
"""
from django.urls import path

from . import discover_views


urlpatterns = [
    path('', discover_views.discover, name='discover'),
]
