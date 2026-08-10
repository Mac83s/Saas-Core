from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .forms import IdentityUserChangeForm, IdentityUserCreationForm
from .models import User


@admin.register(User)
class IdentityUserAdmin(UserAdmin):  # type: ignore[type-arg]
    add_form = IdentityUserCreationForm
    form = IdentityUserChangeForm
    ordering = ("email",)
    list_display = ("email", "status", "is_staff", "date_joined")
    list_filter = ("status", "is_staff", "is_superuser", "groups")
    search_fields = ("email",)
    readonly_fields = ("id", "date_joined", "created_at", "updated_at", "last_login")
    fieldsets = (
        (None, {"fields": ("id", "email", "password")}),
        ("Profil", {"fields": ("status", "locale", "timezone")}),
        (
            "Uprawnienia operatorskie",
            {"fields": ("is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Daty", {"fields": ("last_login", "date_joined", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2", "status", "is_staff"),
            },
        ),
    )
