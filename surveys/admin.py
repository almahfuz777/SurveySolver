from django.contrib import admin

from .models import Survey, Topic


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
