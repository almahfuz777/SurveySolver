"""Routes for the authoring workspace.

Included from surveys/urls.py under the same /surveys/ prefix, so these paths continue from a
survey id just like the lifecycle routes do.
"""
from django.urls import path

from . import views


urlpatterns = [
    path('<uuid:survey_id>/edit/', views.survey_edit, name='survey_edit'),
    path('<uuid:survey_id>/rename/', views.survey_rename, name='survey_rename'),
    path('<uuid:survey_id>/responses/collection/', views.survey_response_collection, name='survey_response_collection'),
    path('<uuid:survey_id>/builder/', views.survey_builder, name='survey_builder'),
    path('<uuid:survey_id>/builder/header/', views.survey_builder_header_update, name='survey_builder_header_update'),
    path('<uuid:survey_id>/builder/banner/', views.survey_banner_update, name='survey_banner_update'),
    path('<uuid:survey_id>/preview/', views.survey_preview, name='survey_preview'),
    path('<uuid:survey_id>/builder/sections/add/', views.section_add, name='section_add'),
    path('<uuid:survey_id>/builder/sections/<uuid:section_id>/update/', views.section_update, name='section_update'),
    path('<uuid:survey_id>/builder/sections/<uuid:section_id>/move/', views.section_move, name='section_move'),
    path('<uuid:survey_id>/builder/sections/<uuid:section_id>/delete/', views.section_delete, name='section_delete'),
    path('<uuid:survey_id>/builder/questions/add/', views.question_add, name='question_add'),
    path('<uuid:survey_id>/builder/questions/<uuid:question_id>/duplicate/', views.question_duplicate, name='question_duplicate'),
    path('<uuid:survey_id>/builder/questions/<uuid:question_id>/reorder/', views.question_reorder, name='question_reorder'),
    path('<uuid:survey_id>/builder/questions/<uuid:question_id>/update/', views.question_update, name='question_update'),
    path('<uuid:survey_id>/builder/questions/<uuid:question_id>/move/', views.question_move, name='question_move'),
    path('<uuid:survey_id>/builder/questions/<uuid:question_id>/delete/', views.question_delete, name='question_delete'),
    path('<uuid:survey_id>/builder/questions/<uuid:question_id>/branches/add/', views.question_branch_add, name='question_branch_add'),
    path('<uuid:survey_id>/builder/branches/<uuid:rule_id>/delete/', views.question_branch_delete, name='question_branch_delete'),
]
