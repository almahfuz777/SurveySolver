from django.urls import path

from . import views


urlpatterns = [
    path(
        '<uuid:survey_id>/',
        views.survey_analytics_dashboard,
        name='survey_analytics',
    ),
]
