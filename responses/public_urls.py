"""The short public link a respondent follows to reach a survey."""
from django.urls import path

from . import views


urlpatterns = [
    path('<slug:slug>/', views.survey_landing, name='respond_survey'),
]
