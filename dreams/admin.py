from django.contrib import admin

from .models import Dream


@admin.register(Dream)
class DreamAdmin(admin.ModelAdmin):
    """Administration des rêves."""

    list_display = ("__str__", "user", "created_at", "emotion", "status")
    list_filter = ("status", "emotion", "created_at")
    search_fields = ("user__username", "transcription")
    readonly_fields = ("created_at",)
