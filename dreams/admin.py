from typing import Any

from django.contrib import admin
from django.db.models import Avg, Count, Q, Sum
from django.http import HttpRequest, HttpResponse

from .models import ApiCall, Dream


@admin.register(Dream)
class DreamAdmin(admin.ModelAdmin):
    """Administration des rêves."""

    list_display = ("__str__", "user", "created_at", "emotion", "status")
    list_filter = ("status", "emotion", "created_at")
    search_fields = ("user__username", "transcription")
    readonly_fields = ("created_at",)


@admin.register(ApiCall)
class ApiCallAdmin(admin.ModelAdmin):
    """Suivi des appels aux API : coût cumulé, erreurs et latence.

    Les appels sont enregistrés automatiquement par `call_api()` : on peut
    les consulter et les filtrer, mais pas les créer ni les modifier.
    """

    list_display = (
        "created_at",
        "service",
        "task",
        "success",
        "http_status",
        "attempts",
        "duration_ms",
        "cost_usd",
    )
    list_filter = ("service", "task", "success", "created_at")
    date_hierarchy = "created_at"

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Les appels sont créés par l'application, jamais à la main."""
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: ApiCall | None = None
    ) -> bool:
        """Un appel enregistré ne se modifie pas (consultation seule)."""
        return False

    def changelist_view(
        self, request: HttpRequest, extra_context: dict[str, Any] | None = None
    ) -> HttpResponse:
        """Ajoute en haut de la liste le résumé des appels affichés.

        Le résumé suit les filtres choisis (service, date…).

        Returns:
            La page de la liste des appels.
        """
        response = super().changelist_view(request, extra_context)
        changelist = getattr(response, "context_data", {}).get("cl")
        if changelist is not None:
            summary = changelist.queryset.aggregate(
                total_cost=Sum("cost_usd"),
                calls=Count("id"),
                failures=Count("id", filter=Q(success=False)),
                average_ms=Avg("duration_ms"),
            )
            calls = summary["calls"]
            summary["failure_rate"] = (
                round(100 * summary["failures"] / calls) if calls else 0
            )
            response.context_data["summary"] = summary
        return response
