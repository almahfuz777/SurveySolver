from django.contrib import admin

from .models import Badge, BadgeAward, GuestRewardClaim, PointTransaction


@admin.register(PointTransaction)
class PointTransactionAdmin(admin.ModelAdmin):
    list_display = ('user', 'amount', 'reason', 'created_at')
    list_filter = ('reason', 'created_at')
    search_fields = ('user__email', 'idempotency_key')
    readonly_fields = (
        'id',
        'user',
        'amount',
        'reason',
        'idempotency_key',
        'metadata',
        'created_at',
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(GuestRewardClaim)
class GuestRewardClaimAdmin(admin.ModelAdmin):
    list_display = ('survey', 'points_snapshot', 'created_at', 'expires_at', 'claimed_at')
    list_filter = ('claimed_at', 'expires_at')
    search_fields = ('survey__title', 'claimed_by__email')
    readonly_fields = (
        'id',
        'submission',
        'survey',
        'points_snapshot',
        'secret_hash',
        'session_key_hash',
        'expires_at',
        'claimed_at',
        'claimed_by',
        'created_at',
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Badge)
class BadgeAdmin(admin.ModelAdmin):
    list_display = ('name', 'completion_threshold')
    search_fields = ('name', 'description')


@admin.register(BadgeAward)
class BadgeAwardAdmin(admin.ModelAdmin):
    list_display = ('badge', 'user', 'awarded_at')
    search_fields = ('badge__name', 'user__email')
    readonly_fields = ('id', 'badge', 'user', 'awarded_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff
