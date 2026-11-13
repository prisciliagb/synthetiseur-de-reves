from django.urls import path
from django.views.generic import RedirectView

from .views import (
    AudioUploadView,
    DreamAnalysisView,
    DreamDeleteView,
    DreamDetailView,
    DreamImageView,
    DreamListView,
    RecordDreamView,
)

app_name = "dreams"

urlpatterns = [
    path("", DreamListView.as_view(), name="list"),
    # Ancienne adresse des statistiques, déplacées dans l'app dashboard :
    # redirigée pour que les anciens liens fonctionnent encore.
    path(
        "statistiques/",
        RedirectView.as_view(pattern_name="dashboard:stats", query_string=True),
    ),
    path("enregistrer/", RecordDreamView.as_view(), name="record"),
    path("enregistrer/audio/", AudioUploadView.as_view(), name="upload_audio"),
    path("<int:pk>/", DreamDetailView.as_view(), name="detail"),
    path("<int:pk>/supprimer/", DreamDeleteView.as_view(), name="delete"),
    # Étapes du traitement, lancées l'une après l'autre par le JavaScript.
    path("<int:pk>/analyser/", DreamAnalysisView.as_view(), name="analysis"),
    path("<int:pk>/image/", DreamImageView.as_view(), name="image"),
]
