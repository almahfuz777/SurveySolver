from django.contrib import admin

from .models import CollaborationLink, SurveyCollaborator


@admin.register(SurveyCollaborator)
class SurveyCollaboratorAdmin(admin.ModelAdmin):
    list_display = ('survey', 'user', 'role', 'added_by', 'created_at')
    list_filter = ('role',)
    search_fields = ('survey__title', 'user__email', 'added_by__email')
    readonly_fields = ('id', 'created_at', 'updated_at')


@admin.register(CollaborationLink)
class CollaborationLinkAdmin(admin.ModelAdmin):
    list_display = ('survey', 'role', 'created_by', 'expires_at', 'revoked_at', 'accepted_count')
    list_filter = ('role', 'revoked_at', 'expires_at')
    search_fields = ('survey__title', 'created_by__email')
    readonly_fields = (
        'id',
        'survey',
        'role',
        'token_hash',
        'created_by',
        'expires_at',
        'revoked_at',
        'accepted_count',
        'last_accepted_at',
        'created_at',
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
