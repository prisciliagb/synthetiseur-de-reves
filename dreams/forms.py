from django import forms
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile

# Signatures (premiers octets) des formats audio produits par les navigateurs :
# Chrome et Firefox enregistrent en WebM ou en Ogg, Safari en MP4.
AUDIO_SIGNATURES = {
    "webm": b"\x1a\x45\xdf\xa3",
    "ogg": b"OggS",
}


def detect_audio_format(audio: UploadedFile) -> str | None:
    """Identifie le format d'un fichier audio à partir de ses premiers octets.

    On ne fait pas confiance au nom ni au type annoncés par le navigateur :
    ils peuvent être falsifiés. Le contenu du fichier, lui, ne ment pas.

    Args:
        audio: Le fichier envoyé.

    Returns:
        "webm", "ogg" ou "mp4" si le format est reconnu, sinon None.
    """
    audio.seek(0)
    header = audio.read(12)
    audio.seek(0)
    for audio_format, signature in AUDIO_SIGNATURES.items():
        if header.startswith(signature):
            return audio_format
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
