from typing import Any

from django import forms
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db.models import QuerySet

from .models import Dream

# Signature (premiers octets) d'un fichier WebM, le format d'enregistrement
# de Chrome, Firefox et Edge. Safari enregistre en MP4 (repéré par « ftyp »).
WEBM_SIGNATURE = b"\x1a\x45\xdf\xa3"


def detect_audio_format(audio: UploadedFile) -> str | None:
    """Identifie le format d'un fichier audio à partir de ses premiers octets.

    On ne fait pas confiance au nom ni au type annoncés par le navigateur :
    ils peuvent être falsifiés. Le contenu du fichier, lui, ne ment pas.

    Args:
        audio: Le fichier envoyé.

    Returns:
        "webm" ou "mp4" si le format est reconnu, sinon None.
    """
    audio.seek(0)
    header = audio.read(12)
    audio.seek(0)
    if header.startswith(WEBM_SIGNATURE):
        return "webm"
    if header[4:8] == b"ftyp":
        return "mp4"
    return None


class AudioRecordingForm(forms.Form):
    """Contrôle l'enregistrement audio envoyé par la page « Raconter un rêve »."""

    audio = forms.FileField(
        error_messages={"required": "Aucun enregistrement n'a été reçu."}
    )

    def clean_audio(self) -> UploadedFile:
        """Vérifie la taille et le format de l'enregistrement.

        Returns:
            Le fichier audio validé.

        Raises:
            ValidationError: Si le fichier est trop lourd ou n'est pas un audio
                enregistré par un navigateur.
        """
        audio = self.cleaned_data["audio"]
        max_size = settings.DREAM_AUDIO_MAX_SIZE
        if audio.size > max_size:
            raise forms.ValidationError(
                f"L'enregistrement est trop lourd (maximum "
                f"{max_size // (1024 * 1024)} Mo)."
            )
        if detect_audio_format(audio) is None:
            raise forms.ValidationError(
                "Ce fichier n'est pas un enregistrement audio valide."
            )
        return audio


def _emotion_choices() -> list[tuple[str, str]]:
    """Renvoie les émotions proposées dans le filtre, chacune avec son emoji.

    Returns:
        Les choix de la liste déroulante, en commençant par « Toutes ».
    """
    choices = [("", "Toutes les émotions")]
    for value, label in Dream.Emotion.choices:
        choices.append((value, f"{Dream.EMOTION_ICONS[value]} {label}"))
    return choices


class DreamFilterForm(forms.Form):
    """Filtres de l'historique : période (du… au…) et émotion.

    Tous les champs sont facultatifs et se combinent. Les filtres passent dans
    l'adresse de la page (méthode GET), ce qui permet de les garder en
    changeant de page et de les réutiliser pour les statistiques.
    """

    start = forms.DateField(
        label="Du",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    end = forms.DateField(
        label="Au",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    emotion = forms.ChoiceField(
        label="Émotion", required=False, choices=_emotion_choices
    )

    def clean(self) -> dict[str, Any]:
        """Vérifie que la période est dans le bon ordre.

        Returns:
            Les données validées.

        Raises:
            ValidationError: Si la date de début est après la date de fin.
        """
        cleaned_data = super().clean()
        start = cleaned_data.get("start")
        end = cleaned_data.get("end")
        if start and end and start > end:
            raise forms.ValidationError(
                "La date de début doit être avant la date de fin."
            )
        return cleaned_data

    def filter(self, dreams: QuerySet[Dream]) -> QuerySet[Dream]:
        """Applique les filtres choisis à une liste de rêves.

        Si les filtres sont invalides, la liste est renvoyée sans filtre : le
        formulaire affiche alors l'erreur.

        Args:
            dreams: Les rêves à filtrer.

        Returns:
            Les rêves qui correspondent à tous les filtres remplis.
        """
        if not self.is_valid():
            return dreams
        data = self.cleaned_data
        # « __date » compare le jour, dans le fuseau horaire du site (Paris).
        if data["start"]:
            dreams = dreams.filter(created_at__date__gte=data["start"])
        if data["end"]:
            dreams = dreams.filter(created_at__date__lte=data["end"])
        if data["emotion"]:
            dreams = dreams.filter(emotion=data["emotion"])
        return dreams

    def is_filtering(self) -> bool:
        """Indique si au moins un filtre valide est rempli."""
        return self.is_valid() and any(self.cleaned_data.values())
