from django.contrib import admin
from django.db import transaction

from .models import MatrixRow, Question, QuestionChoice, Section, Survey, SurveyVersion, Topic


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Survey)
class SurveyAdmin(admin.ModelAdmin):
    list_display = ('title', 'owner', 'status', 'visibility', 'updated_at')
    list_filter = ('status', 'visibility', 'identity_mode', 'topics')
    search_fields = ('title', 'summary', 'owner__email')
    readonly_fields = ('id', 'slug', 'created_at', 'updated_at', 'published_at', 'closed_at')
    filter_horizontal = ('topics',)

    def delete_queryset(self, request, queryset):
        # Route bulk deletion through Survey.delete() so the PROTECTed identity
        # hierarchy is torn down in order; the default collector batch fails.
        # One transaction over the whole selection: if any survey is protected,
        # none are deleted.
        with transaction.atomic():
            for survey in queryset:
                survey.delete()


class SectionInline(admin.TabularInline):
    model = Section
    extra = 0
    # Ordering and randomization live on SectionIdentity, so a snapshot row only
    # offers the content that belongs to this version.
    fields = ('title',)


@admin.register(SurveyVersion)
class SurveyVersionAdmin(admin.ModelAdmin):
    list_display = ('survey', 'number', 'status', 'revision', 'updated_at')
    list_filter = ('status',)
    search_fields = ('survey__title', 'survey__owner__email')
    readonly_fields = ('id', 'created_at', 'updated_at', 'published_at')
    inlines = (SectionInline,)


class QuestionChoiceInline(admin.TabularInline):
    model = QuestionChoice
    extra = 0


class MatrixRowInline(admin.TabularInline):
    model = MatrixRow
    extra = 0


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    # Placement, required state and randomization live on QuestionIdentity, so a
    # snapshot row only offers the content that belongs to this version.
    list_display = ('prompt', 'type', 'section')
    list_filter = ('type',)
    search_fields = ('prompt', 'section__version__survey__title')
    inlines = (QuestionChoiceInline, MatrixRowInline)


# Live branching, response limits and targeting are owned by SurveyBranchRule, SurveyVersion.response_limit and SurveyEligibilityCriteria.
# The version-scoped tables they replaced were dropped in migration 0013.
