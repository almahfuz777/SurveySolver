from django.urls import path

from . import builder_views, views


urlpatterns = [
    path('', views.survey_list, name='survey_list'),
    path('new/', views.survey_create, name='survey_create'),
    path('<uuid:survey_id>/', views.survey_detail, name='survey_detail'),
    path('<uuid:survey_id>/edit/', views.survey_edit, name='survey_edit'),
    path('<uuid:survey_id>/archive/', views.survey_archive, name='survey_archive'),
    path('<uuid:survey_id>/responses/collection/', views.survey_response_collection, name='survey_response_collection'),
    path('<uuid:survey_id>/rename/', views.survey_rename, name='survey_rename'),
    path('<uuid:survey_id>/builder/header/', views.survey_builder_header_update, name='survey_builder_header_update'),
    path('<uuid:survey_id>/builder/banner/', views.survey_banner_update, name='survey_banner_update'),
    path('<uuid:survey_id>/delete/', views.survey_delete, name='survey_delete'),
    path('<uuid:survey_id>/restore/', views.survey_restore, name='survey_restore'),
    path('<uuid:survey_id>/purge/', views.survey_purge, name='survey_purge'),
    path('<uuid:survey_id>/publish/', views.survey_publish, name='survey_publish'),
    path('<uuid:survey_id>/publish/review/', views.survey_publish_review, name='survey_publish_review'),
    path('<uuid:survey_id>/draft/discard/', views.survey_discard_draft, name='survey_discard_draft'),
    path('<uuid:survey_id>/versions/<uuid:version_id>/restore/', views.survey_version_restore, name='survey_version_restore'),
    path('<uuid:survey_id>/versions/<uuid:version_id>/delete/', views.survey_version_delete, name='survey_version_delete'),
    path('<uuid:survey_id>/builder/', builder_views.survey_builder, name='survey_builder'),
    path('<uuid:survey_id>/preview/', builder_views.survey_preview, name='survey_preview'),
    path('<uuid:survey_id>/builder/questions/<uuid:question_id>/branches/add/', builder_views.question_branch_add, name='question_branch_add'),
    path('<uuid:survey_id>/builder/branches/<uuid:rule_id>/delete/', builder_views.question_branch_delete, name='question_branch_delete'),
    path('<uuid:survey_id>/builder/sections/add/', builder_views.section_add, name='section_add'),
    path('<uuid:survey_id>/builder/sections/<uuid:section_id>/update/', builder_views.section_update, name='section_update'),
    path('<uuid:survey_id>/builder/sections/<uuid:section_id>/move/', builder_views.section_move, name='section_move'),
    path('<uuid:survey_id>/builder/sections/<uuid:section_id>/delete/', builder_views.section_delete, name='section_delete'),
    path('<uuid:survey_id>/builder/questions/add/', builder_views.question_add, name='question_add'),
    path('<uuid:survey_id>/builder/questions/<uuid:question_id>/duplicate/', builder_views.question_duplicate, name='question_duplicate'),
    path('<uuid:survey_id>/builder/questions/<uuid:question_id>/reorder/', builder_views.question_reorder, name='question_reorder'),
    path('<uuid:survey_id>/builder/questions/<uuid:question_id>/update/', builder_views.question_update, name='question_update'),
    path('<uuid:survey_id>/builder/questions/<uuid:question_id>/move/', builder_views.question_move, name='question_move'),
    path('<uuid:survey_id>/builder/questions/<uuid:question_id>/delete/', builder_views.question_delete, name='question_delete'),
]
