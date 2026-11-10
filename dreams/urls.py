from django.urls import path

from .views import DreamDetailView, DreamListView

app_name = "dreams"

urlpatterns = [
    path("", DreamListView.as_view(), name="list"),
    path("<int:pk>/", DreamDetailView.as_view(), name="detail"),
]
