from decimal import Decimal
from typing import ClassVar

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .storage import CloudinaryStorage


class Dream(models.Model):
    """Un rêve raconté par un utilisateur, avec les résultats de son analyse.

    Attributes:
        user: Propriétaire du rêve.
        created_at: Date et heure d'enregistrement du rêve.
        transcription: Texte du rêve obtenu par la transcription audio.
        emotion: Émotion dominante détectée dans le rêve.
        confidence: Score de confiance de la classification, entre 0 et 1.
        image_prompt: Description envoyée à l'IA pour générer l'image.
        image: Image générée à partir du rêve.
        status: Étape du traitement du rêve.
    """

    class Emotion(models.TextChoices):
        """Émotions que la classification peut détecter."""

        HAPPY = "happy", "Heureux"
        SAD = "sad", "Triste"
        STRESSFUL = "stressful", "Stressant"
        SCARY = "scary", "Effrayant"
        STRANGE = "strange", "Étrange"
        NEUTRAL = "neutral", "Neutre"

    # Côté (en pixels) de la miniature de l'image dans l'historique.
    THUMBNAIL_SIZE: ClassVar[int] = 120

    class Status(models.TextChoices):
        """Étapes du traitement d'un rêve."""

        PENDING = "pending", "En attente"
        PROCESSING = "processing", "En cours de traitement"
        DONE = "done", "Terminé"
        FAILED = "failed", "Échec"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="dreams",
        verbose_name="utilisateur",
    )
    created_at = models.DateTimeField("date", auto_now_add=True)
    transcription = models.TextField("transcription", blank=True)
    emotion = models.CharField(
        "émotion", max_length=20, choices=Emotion.choices, blank=True
    )
    confidence = models.FloatField(
        "score de confiance",
        null=True,
        blank=True,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
    )
    image_prompt = models.TextField("prompt image", blank=True)
    image = models.ImageField("image", upload_to="dreams/%Y/%m/", blank=True)
    status = models.CharField(
        "statut", max_length=20, choices=Status.choices, default=Status.PENDING
    )

    class Meta:
        verbose_name = "rêve"
        verbose_name_plural = "rêves"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        """Affiche le rêve par son auteur et sa date."""
        return f"Rêve de {self.user} du {self.created_at:%d/%m/%Y}"

    @property
    def thumbnail_url(self) -> str:
        """Renvoie l'adresse d'une version réduite de l'image du rêve.

        Sur Cloudinary, l'image est redimensionnée par Cloudinary lui-même :
        l'historique charge une petite image au lieu de l'image complète. En
        local (stockage sur disque), on renvoie l'image complète.

        Returns:
            L'adresse de la miniature, ou une chaîne vide s'il n'y a pas d'image.
        """
        if not self.image:
            return ""
        storage = self.image.storage
        if isinstance(storage, CloudinaryStorage):
            return storage.thumbnail_url(self.image.name, self.THUMBNAIL_SIZE)
        return self.image.url


class ApiCall(models.Model):
    """Un appel à une API externe (Groq, Replicate), pour suivre coûts et erreurs.

    Aucune donnée personnelle n'est enregistrée : ni l'utilisateur, ni le
    texte du rêve. Seulement ce qu'il faut pour surveiller la latence, les
    erreurs et le budget.

    Attributes:
        created_at: Date et heure de l'appel.
        service: Fournisseur appelé (« Groq », « Replicate »).
        task: Tâche demandée (« Transcription », « Analyse », « Image »…).
        success: Vrai si l'API a fini par répondre avec succès.
        http_status: Dernier code HTTP reçu, ou vide si aucune réponse.
        attempts: Nombre de tentatives (0 si la clé d'API manque).
        duration_ms: Durée totale, nouvelles tentatives comprises.
        cost_usd: Coût estimé en dollars, d'après les tarifs des réglages.
    """

    created_at = models.DateTimeField("date", auto_now_add=True, db_index=True)
    service = models.CharField("service", max_length=30)
    task = models.CharField("tâche", max_length=50)
    success = models.BooleanField("succès")
    http_status = models.PositiveSmallIntegerField("code HTTP", null=True, blank=True)
    attempts = models.PositiveSmallIntegerField("tentatives")
    duration_ms = models.PositiveIntegerField("durée (ms)")
    cost_usd = models.DecimalField(
        "coût estimé ($)", max_digits=10, decimal_places=6, default=Decimal(0)
    )

    class Meta:
        verbose_name = "appel API"
        verbose_name_plural = "appels API"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        """Affiche l'appel par son service, sa tâche et sa date."""
        return f"{self.service} · {self.task} · {self.created_at:%d/%m/%Y %H:%M}"
