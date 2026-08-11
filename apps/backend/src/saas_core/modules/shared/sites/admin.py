from django.contrib import admin

from .models import Domain


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = (
        "hostname",
        "kind",
        "status",
        "tls_status",
        "is_canonical",
        "last_checked_at",
        "last_verified_at",
    )
    list_filter = ("kind", "status", "tls_status", "is_canonical")
    search_fields = ("=hostname", "=site__id", "=organization__id")
    readonly_fields = (
        "id",
        "organization",
        "site",
        "hostname",
        "kind",
        "status",
        "tls_status",
        "is_canonical",
        "last_checked_at",
        "last_verified_at",
        "next_check_at",
        "dns_error_code",
        "consecutive_transient_errors",
        "tls_last_requested_at",
        "released_at",
        "quarantine_until",
        "created_by",
        "created_at",
        "updated_at",
    )
    exclude = ("verification_token", "request_hash", "idempotency_key")

    def has_add_permission(self, request):  # type: ignore[no-untyped-def]
        return False

    def has_change_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return request.user.is_staff

    def has_delete_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False
