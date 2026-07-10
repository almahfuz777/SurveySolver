from django.urls import path

from . import views


urlpatterns = [
    path('', views.survey_list, name='survey_list'),
    path('new/', views.survey_create, name='survey_create'),
    path('<uuid:survey_id>/', views.survey_detail, name='survey_detail'),
    path('<uuid:survey_id>/edit/', views.survey_edit, name='survey_edit'),
    path('<uuid:survey_id>/archive/', views.survey_archive, name='survey_archive'),
]
