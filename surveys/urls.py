from django.urls import path

from . import views


urlpatterns = [
    path('', views.survey_list, name='survey_list'),
    path('new/', views.survey_create, name='survey_create'),
    path('<uuid:survey_id>/', views.survey_detail, name='survey_detail'),
    path('<uuid:survey_id>/edit/', views.survey_edit, name='survey_edit'),
    path('<uuid:survey_id>/archive/', views.survey_archive, name='survey_archive'),
    path('<uuid:survey_id>/builder/', views.survey_builder, name='survey_builder'),
    path('<uuid:survey_id>/preview/', views.survey_preview, name='survey_preview'),
    path('<uuid:survey_id>/builder/logic/', views.survey_logic, name='survey_logic'),
    path('<uuid:survey_id>/builder/sections/add/', views.section_add, name='section_add'),
    path('<uuid:survey_id>/builder/sections/<uuid:section_id>/update/', views.section_update, name='section_update'),
    path('<uuid:survey_id>/builder/sections/<uuid:section_id>/move/', views.section_move, name='section_move'),
    path('<uuid:survey_id>/builder/sections/<uuid:section_id>/delete/', views.section_delete, name='section_delete'),
    path('<uuid:survey_id>/builder/questions/add/', views.question_add, name='question_add'),
    path('<uuid:survey_id>/builder/questions/<uuid:question_id>/update/', views.question_update, name='question_update'),
    path('<uuid:survey_id>/builder/questions/<uuid:question_id>/move/', views.question_move, name='question_move'),
    path('<uuid:survey_id>/builder/questions/<uuid:question_id>/delete/', views.question_delete, name='question_delete'),
]
