"""A respondent's own record of what they have answered and earned."""
from django.urls import path

from . import views


urlpatterns = [
    path('', views.my_responses, name='my_responses'),
]
