from django.contrib import admin

from .models import Question, QuestionChoice, Section, Survey, SurveyVersion, Topic


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


class SectionInline(admin.TabularInline):
    model = Section
    extra = 0
    fields = ('title', 'order')


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


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('prompt', 'type', 'section', 'order', 'required')
    list_filter = ('type', 'required')
    search_fields = ('prompt', 'section__version__survey__title')
    inlines = (QuestionChoiceInline,)
