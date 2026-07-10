from django.contrib import admin

from .models import PointTransaction


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

    def has_change_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff
