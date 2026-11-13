"""Test de charge du Synthétiseur de rêves avec Locust (issue #18).

Chaque utilisateur simulé se connecte avec un compte « charge-NN », puis
navigue comme un vrai utilisateur : historique, filtres, page d'un rêve,
statistiques, accueil.

Il n'enregistre jamais de rêve : cela appellerait Groq et Replicate, qui sont
payants, et on mesurerait leur vitesse plutôt que celle du site.

Préparation et lancement : voir docs/test-de-charge.md.
"""

import os
import random
import re

from locust import HttpUser, between, task

# Mot de passe et nombre des comptes créés par `donnees_test_de_charge`.
PASSWORD = os.environ.get("LOADTEST_PASSWORD", "")
ACCOUNT_COUNT = int(os.environ.get("LOADTEST_ACCOUNTS", "20"))
EMOTIONS = ["happy", "sad", "stressful", "scary", "strange", "neutral"]

CSRF_INPUT = re.compile(r'name="csrfmiddlewaretoken" value="([^"]+)"')
DREAM_LINK = re.compile(r'href="/reves/(\d+)/"')


class DreamerUser(HttpUser):
    """Un utilisateur connecté qui consulte ses rêves."""

    # Pause de 1 à 3 secondes entre deux pages, comme une vraie personne.
    wait_time = between(1, 3)

    def on_start(self) -> None:
        """Se connecte avec un des comptes du test de charge."""
        if not PASSWORD:
            raise RuntimeError("Définissez LOADTEST_PASSWORD avant de lancer Locust.")
        self.dream_ids: list[str] = []
        login_page = self.client.get("/comptes/connexion/", name="Connexion (page)")
        token = CSRF_INPUT.search(login_page.text).group(1)
        username = f"charge-{random.randint(1, ACCOUNT_COUNT):02d}"
        with self.client.post(
            "/comptes/connexion/",
            data={
                "username": username,
                "password": PASSWORD,
                "csrfmiddlewaretoken": token,
            },
            headers={"Referer": self.host + "/comptes/connexion/"},
            name="Connexion (envoi)",
            catch_response=True,
        ) as response:
            # Connexion réussie = redirection vers l'historique. Sinon, Django
            # réaffiche le formulaire : on le compte comme une erreur.
            if "/comptes/connexion/" in response.url:
                response.failure("Connexion refusée")

    @task(4)
    def history(self) -> None:
        """Ouvre l'historique et retient les rêves affichés."""
        response = self.client.get("/reves/", name="Historique")
        self.dream_ids = DREAM_LINK.findall(response.text) or self.dream_ids

    @task(2)
    def history_page_2(self) -> None:
        """Ouvre la deuxième page de l'historique."""
        self.client.get("/reves/?page=2", name="Historique (page 2)")

    @task(2)
    def filtered_history(self) -> None:
        """Filtre l'historique par émotion."""
        emotion = random.choice(EMOTIONS)
        self.client.get(f"/reves/?emotion={emotion}", name="Historique (filtre)")

    @task(3)
    def dream_detail(self) -> None:
        """Ouvre la page d'un de ses rêves."""
        if self.dream_ids:
            dream_id = random.choice(self.dream_ids)
            self.client.get(f"/reves/{dream_id}/", name="Page d'un rêve")

    @task(2)
    def statistics(self) -> None:
        """Ouvre les statistiques."""
        self.client.get("/reves/statistiques/", name="Statistiques")

    @task(1)
    def home(self) -> None:
        """Revient à l'accueil."""
        self.client.get("/", name="Accueil")

    @task(1)
    def health(self) -> None:
        """Interroge /health, comme un outil de surveillance."""
        self.client.get("/health", name="/health")
