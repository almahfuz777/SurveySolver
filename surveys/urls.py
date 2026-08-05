from django.urls import include, path

from . import views


urlpatterns = [
    path('', views.survey_list, name='survey_list'),
    path('new/', views.survey_create, name='survey_create'),
    path('<uuid:survey_id>/', views.survey_detail, name='survey_detail'),
    path('<uuid:survey_id>/archive/', views.survey_archive, name='survey_archive'),
    path('<uuid:survey_id>/delete/', views.survey_delete, name='survey_delete'),
    path('<uuid:survey_id>/restore/', views.survey_restore, name='survey_restore'),
    path('<uuid:survey_id>/purge/', views.survey_purge, name='survey_purge'),
    path('<uuid:survey_id>/publish/', views.survey_publish, name='survey_publish'),
    path('<uuid:survey_id>/publish/review/', views.survey_publish_review, name='survey_publish_review'),
    path('<uuid:survey_id>/draft/discard/', views.survey_discard_draft, name='survey_discard_draft'),
    path('<uuid:survey_id>/versions/<uuid:version_id>/restore/', views.survey_version_restore, name='survey_version_restore'),
    path('<uuid:survey_id>/versions/<uuid:version_id>/delete/', views.survey_version_delete, name='survey_version_delete'),

    # Builder package paths
    path('', include('surveys.builder.urls')),
]
