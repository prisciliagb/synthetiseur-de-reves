from django.urls import path

from .views import (
    AudioUploadView,
    DreamAnalysisView,
    DreamDeleteView,
    DreamDetailView,
    DreamImageView,
    DreamListView,
    DreamStatsView,
    RecordDreamView,
)

app_name = "dreams"

urlpatterns = [
    path("", DreamListView.as_view(), name="list"),
    path("statistiques/", DreamStatsView.as_view(), name="stats"),
    path("enregistrer/", RecordDreamView.as_view(), name="record"),
    path("enregistrer/audio/", AudioUploadView.as_view(), name="upload_audio"),
    path("<int:pk>/", DreamDetailView.as_view(), name="detail"),
    path("<int:pk>/supprimer/", DreamDeleteView.as_view(), name="delete"),
    # Étapes du traitement, lancées l'une après l'autre par le JavaScript.
    path("<int:pk>/analyser/", DreamAnalysisView.as_view(), name="analysis"),
    path("<int:pk>/image/", DreamImageView.as_view(), name="image"),
]
