"""Statistiques des rêves : nombre de rêves par semaine et répartition des émotions.

Les comptages sont faits par la base de données (`Count`, `TruncWeek`) : on ne
charge pas tous les rêves en mémoire. La fonction reçoit une liste de rêves déjà
filtrée (utilisateur, période, émotion), comme l'historique.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import Count, QuerySet
from django.db.models.functions import TruncWeek

from dreams.models import Dream


@dataclass(frozen=True)
class EmotionCount:
    """Nombre de rêves d'une émotion.

    Attributes:
        value: La valeur enregistrée en base (ex. : « scary »).
        label: Le nom affiché (ex. : « Effrayant »).
        count: Le nombre de rêves de cette émotion.
        percent: La part de ces rêves parmi les rêves analysés, en %.
    """

    value: str
    label: str
    count: int
    percent: int


@dataclass(frozen=True)
class DreamStats:
    """Statistiques d'une liste de rêves.

    Attributes:
        total: Le nombre de rêves.
        analyzed: Le nombre de rêves dont l'émotion est connue.
        weeks: Le nombre de rêves de chaque semaine (date du lundi, nombre),
            de la plus ancienne à la plus récente, semaines vides comprises.
        emotions: Toutes les émotions, de la plus fréquente à la moins fréquente.
        dominant: Les émotions les plus fréquentes (plusieurs en cas
            d'égalité), ou une liste vide si aucun rêve n'est analysé.
    """

    total: int
    analyzed: int
    weeks: list[tuple[date, int]]
    emotions: list[EmotionCount]
    dominant: list[EmotionCount]


def dreams_per_week(dreams: QuerySet[Dream]) -> list[tuple[date, int]]:
    """Compte les rêves de chaque semaine.

    Les semaines sans rêve sont ajoutées avec 0 : sans elles, le graphique
    collerait deux semaines éloignées et donnerait une fausse impression.

    Args:
        dreams: Les rêves à compter.

    Returns:
        Une liste (lundi de la semaine, nombre de rêves), dans l'ordre.
    """
    rows = (
        dreams.annotate(week=TruncWeek("created_at"))
        .values("week")
        .annotate(count=Count("id"))
        .order_by("week")
    )
    # TruncWeek renvoie le lundi à minuit, dans le fuseau horaire du site.
    counts = {row["week"].date(): row["count"] for row in rows}
    if not counts:
        return []
    weeks = []
    monday, last = min(counts), max(counts)
    while monday <= last:
        weeks.append((monday, counts.get(monday, 0)))
        monday += timedelta(weeks=1)
    return weeks


def emotion_counts(dreams: QuerySet[Dream]) -> list[EmotionCount]:
    """Compte les rêves de chaque émotion.

    Toutes les émotions sont présentes, même à 0, pour qu'on voie aussi les
    émotions absentes. Les rêves pas encore analysés ne sont pas comptés.

    Args:
        dreams: Les rêves à compter.

    Returns:
        Les émotions, de la plus fréquente à la moins fréquente.
    """
    rows = dreams.exclude(emotion="").values("emotion").annotate(count=Count("id"))
    counts = {row["emotion"]: row["count"] for row in rows.order_by()}
    analyzed = sum(counts.values())
    emotions = [
        EmotionCount(
            value=value,
            label=label,
            count=counts.get(value, 0),
            percent=round(100 * counts.get(value, 0) / analyzed) if analyzed else 0,
        )
        for value, label in Dream.Emotion.choices
    ]
    # sorted() garde l'ordre du modèle entre deux émotions à égalité.
    return sorted(emotions, key=lambda emotion: emotion.count, reverse=True)


def compute_stats(dreams: QuerySet[Dream]) -> DreamStats:
    """Calcule toutes les statistiques d'une liste de rêves.

    Args:
        dreams: Les rêves, déjà filtrés.

    Returns:
        Les statistiques de ces rêves.
    """
    emotions = emotion_counts(dreams)
    analyzed = sum(emotion.count for emotion in emotions)
    top = emotions[0].count
    dominant = [emotion for emotion in emotions if emotion.count == top] if top else []
    return DreamStats(
        total=dreams.count(),
        analyzed=analyzed,
        weeks=dreams_per_week(dreams),
        emotions=emotions,
        dominant=dominant,
    )
