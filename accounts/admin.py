from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """Administration des utilisateurs, avec la date de consentement RGPD."""

    fieldsets = (
        *UserAdmin.fieldsets,
        ("RGPD", {"fields": ("rgpd_consent_at",)}),
    )
    list_display = ("username", "email", "rgpd_consent_at", "is_staff")
