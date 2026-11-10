from django.urls import path

from .views import (
    AudioUploadView,
    DreamDetailView,
    DreamListView,
    RecordDreamView,
)

app_name = "dreams"

urlpatterns = [
    path("", DreamListView.as_view(), name="list"),
    path("enregistrer/", RecordDreamView.as_view(), name="record"),
    path("enregistrer/audio/", AudioUploadView.as_view(), name="upload_audio"),
    path("<int:pk>/", DreamDetailView.as_view(), name="detail"),
]
