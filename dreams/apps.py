from django.apps import AppConfig


class DreamsConfig(AppConfig):
    """Configuration de l'application dreams."""

    name = "dreams"

    def ready(self) -> None:
        """Branche les signaux de l'application au démarrage de Django."""
        from . import signals  # noqa: F401
