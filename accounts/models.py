from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Utilisateur de l'application.

    Étend l'utilisateur Django pour conserver la preuve du consentement RGPD
    donné à l'inscription.

    Attributes:
        email: Adresse e-mail, obligatoire et unique.
        rgpd_consent_at: Date et heure auxquelles l'utilisateur a accepté le
            traitement de ses données personnelles.
    """

    email = models.EmailField("adresse e-mail", unique=True)
    rgpd_consent_at = models.DateTimeField(
        "consentement RGPD donné le", null=True, blank=True
    )
