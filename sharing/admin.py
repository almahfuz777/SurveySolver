from django.contrib import admin

from .models import (
    CollaborationLink,
    CollaboratorInvitation,
    RespondentInvitation,
    SurveyCollaborator,
)


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


@admin.register(CollaboratorInvitation)
class CollaboratorInvitationAdmin(admin.ModelAdmin):
    list_display = ('email', 'survey', 'role', 'delivery_status', 'expires_at', 'accepted_at')
    list_filter = ('role', 'delivery_status', 'revoked_at', 'accepted_at')
    search_fields = ('email', 'survey__title', 'created_by__email')
    readonly_fields = (
        'id',
        'survey',
        'email',
        'role',
        'token_hash',
        'created_by',
        'expires_at',
        'revoked_at',
        'accepted_at',
        'accepted_by',
        'delivery_status',
        'delivery_error',
        'sent_at',
        'created_at',
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RespondentInvitation)
class RespondentInvitationAdmin(admin.ModelAdmin):
    list_display = ('email', 'survey', 'delivery_status', 'expires_at', 'consumed_at')
    list_filter = ('delivery_status', 'revoked_at', 'consumed_at')
    search_fields = ('email', 'survey__title', 'created_by__email')
    readonly_fields = (
        'id',
        'survey',
        'email',
        'token_hash',
        'created_by',
        'expires_at',
        'revoked_at',
        'consumed_at',
        'bound_submission_id',
        'delivery_status',
        'delivery_error',
        'sent_at',
        'created_at',
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
