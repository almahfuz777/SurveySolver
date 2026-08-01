"""Reading and exporting the responses a survey has collected.

Mounted under the /surveys/ prefix because these pages hang off a survey the user manages.
"""
from django.urls import path

from . import creator_views


urlpatterns = [
    path('<uuid:survey_id>/responses/', creator_views.response_list, name='creator_response_list'),
    path('<uuid:survey_id>/responses/export.csv', creator_views.response_export_csv, name='response_export_csv'),
    path('<uuid:survey_id>/responses/export.json', creator_views.response_export_json, name='response_export_json'),
    path('<uuid:survey_id>/responses/export.xlsx', creator_views.response_export_excel, name='response_export_excel'),
    path('<uuid:survey_id>/responses/<uuid:submission_id>/', creator_views.response_detail, name='creator_response_detail'),
    path('<uuid:survey_id>/responses/<uuid:submission_id>/delete/', creator_views.response_delete, name='creator_response_delete'),
]
