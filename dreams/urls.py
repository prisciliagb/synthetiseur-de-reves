from django.urls import path

from .views import DreamListView

app_name = "dreams"

urlpatterns = [
    path("", DreamListView.as_view(), name="list"),
]
