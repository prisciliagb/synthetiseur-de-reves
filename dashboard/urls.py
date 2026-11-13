from django.urls import path

from .views import StatsView

app_name = "dashboard"

urlpatterns = [
    path("", StatsView.as_view(), name="stats"),
]
