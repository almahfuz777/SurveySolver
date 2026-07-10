from django.contrib import admin

from .models import Answer, Submission


class AnswerInline(admin.TabularInline):
    model = Answer
    extra = 0
    readonly_fields = ('id', 'question', 'value', 'created_at')
    can_delete = False


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ('survey', 'status', 'source', 'respondent', 'started_at', 'completed_at')
    list_filter = ('status', 'source')
    search_fields = ('survey__title', 'respondent__email')
    readonly_fields = (
        'id',
        'survey',
        'version',
        'respondent',
        'session_key_hash',
        'source',
        'status',
        'presentation',
        'started_at',
        'updated_at',
        'completed_at',
    )
    inlines = (AnswerInline,)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
