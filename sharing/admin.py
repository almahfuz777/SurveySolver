from django.contrib import admin

from .models import SurveyCollaborator


@admin.register(SurveyCollaborator)
class SurveyCollaboratorAdmin(admin.ModelAdmin):
    list_display = ('survey', 'user', 'role', 'added_by', 'created_at')
    list_filter = ('role',)
    search_fields = ('survey__title', 'user__email', 'added_by__email')
    readonly_fields = ('id', 'created_at', 'updated_at')
