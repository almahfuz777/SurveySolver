from django.urls import path

from . import views


urlpatterns = [
    path('s/<slug:slug>/', views.survey_landing, name='respond_survey'),
    path('responses/<uuid:submission_id>/', views.submission_form, name='response_form'),
    path(
        'responses/<uuid:submission_id>/complete/',
        views.submission_complete,
        name='response_complete',
    ),
]
