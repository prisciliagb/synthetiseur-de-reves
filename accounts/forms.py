from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.utils import timezone

from .models import User


class SignUpForm(UserCreationForm):
    """Formulaire d'inscription avec consentement RGPD obligatoire."""

    rgpd_consent = forms.BooleanField(
        required=True,
        label=(
            "J'accepte que mes rêves et mes enregistrements audio soient "
            "traités pour générer leur transcription, leur analyse et leur "
            "illustration."
        ),
        error_messages={
            "required": "Vous devez accepter le traitement de vos données "
            "pour créer un compte."
        },
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def save(self, commit: bool = True) -> User:
        """Crée l'utilisateur en enregistrant la date du consentement RGPD.

        Args:
            commit: Si True, enregistre l'utilisateur en base.

        Returns:
            L'utilisateur créé.
        """
        user = super().save(commit=False)
        user.rgpd_consent_at = timezone.now()
        if commit:
            user.save()
        return user
