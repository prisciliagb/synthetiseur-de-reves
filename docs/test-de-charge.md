# Test de charge

Mesure du comportement du Synthétiseur de rêves quand plusieurs utilisateurs
s'en servent en même temps (issue #18). Test réalisé le 13/11/2026.

## Protocole

**Outil :** [Locust](https://locust.io) 2.47, script [`loadtests/locustfile.py`](../loadtests/locustfile.py).

**Parcours simulé.** Chaque utilisateur virtuel se connecte avec son propre compte,
puis enchaîne les pages avec une pause de 1 à 3 s entre deux pages, comme une
vraie personne. Le poids de chaque page indique sa fréquence relative.

| Page | Poids |
|---|---|
| Historique | 4 |
| Page d'un rêve | 3 |
| Historique, page 2 | 2 |
| Historique filtré par émotion | 2 |
| Statistiques | 2 |
| Accueil | 1 |
| `/health` | 1 |

**Données.** 20 comptes de test avec 30 rêves chacun, répartis sur 60 jours.
Ils sont créés par `manage.py donnees_test_de_charge` sans appeler aucune API,
puis supprimés après le test.

**Serveur, proche de la production :**
- Gunicorn avec 2 processus de 4 fils (comme sur Render), `DEBUG=False` ;
- PostgreSQL 17, dans Docker ;
- **aucune clé d'API** : `/health` le confirme avant le test.

**Le parcours n'enregistre pas de rêve.** Un enregistrement appelle Groq et
Replicate : le test aurait coûté de l'argent, et il aurait mesuré la vitesse de
ces services plutôt que celle du site. La dernière section traite ce cas à part.

**Paliers.** 10, 50, 100 puis 300 utilisateurs simultanés, pendant 1 minute
chacun (1 min 30 pour 300).

## Résultats

Temps de réponse, toutes pages confondues :

| Utilisateurs | Requêtes | Erreurs | Requêtes/s | Médiane | 95e centile | 99e centile | Maximum |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 306 | 1 | 5,2 | 25 ms | 150 ms | – | 460 ms |
| 50 | 1 512 | 1 | 25,6 | 14 ms | 32 ms | – | 476 ms |
| 100 | 2 881 | 3 | 48,7 | 11 ms | 39 ms | – | 583 ms |
| 100, avec `--keep-alive 5` | 2 892 | **0** | 48,9 | 11 ms | 55 ms | – | – |
| 300, avec `--keep-alive 5` | 12 613 | **0** | 141,2 | 9 ms | 260 ms | 740 ms | 1 443 ms |

Détail à 300 utilisateurs :

| Page | Médiane | 95e centile |
|---|---:|---:|
| Page d'un rêve | 8 ms | 18 ms |
| Historique | 9 ms | 140 ms |
| Statistiques | 9 ms | 99 ms |
| Connexion (envoi du formulaire) | 710 ms | 1 000 ms |

À 10 utilisateurs, le 95e centile est plus élevé (150 ms), parce que les
connexions représentent une plus grande part des requêtes.

Pendant le test, le serveur web n'a jamais dépassé 132 Mo de mémoire. C'est
largement sous les 512 Mo de l'offre gratuite de Render.

## Analyse

- **Les pages répondent très vite.** La médiane reste sous 15 ms jusqu'à 300
  utilisateurs. L'historique et les statistiques font leurs calculs dans la
  base de données (pagination, `Count`, `TruncWeek`), sans charger tous les
  rêves en mémoire.
- **La connexion est l'étape la plus lente, et c'est voulu.** Django protège
  les mots de passe avec PBKDF2 (plus d'un million d'itérations). Ce calcul est
  volontairement coûteux : il ralentit d'autant une attaque par force brute.
  Sous forte charge, c'est lui qui occupe le plus le processeur.
- **La dégradation commence vers 300 utilisateurs.** La médiane ne bouge pas,
  mais 5 % des requêtes dépassent 260 ms. Elles attendent qu'un des 8 fils
  de Gunicorn se libère, surtout pendant l'arrivée des utilisateurs, quand
  beaucoup de connexions ont lieu en même temps.
- **Les rares erreurs venaient d'un réglage de Gunicorn, pas de l'application.**
  Les erreurs des trois premiers paliers étaient des connexions coupées
  (`RemoteDisconnected`), sans aucune erreur dans les logs du serveur. Par
  défaut, Gunicorn ferme une connexion inactive au bout de 2 s, alors que
  Locust la réutilise après une pause de 1 à 3 s. Quand les deux arrivent au
  même moment, la requête est perdue.
  - Avec `--keep-alive 5`, il n'y a plus **aucune erreur**, à 100 comme à 300
    utilisateurs.
  - Ce réglage a été ajouté à `render.yaml`.

## Limites du test

- **La machine n'est pas celle de la production.** Le test tourne sur un Mac
  récent, alors que l'offre gratuite de Render donne une fraction de processeur
  et 512 Mo de mémoire. En ligne, il faut s'attendre à des temps nettement plus
  longs : le test pourra être refait sur Render après le déploiement.
- **Locust et le serveur tournent sur la même machine**, et se partagent
  donc le processeur.
- **L'enregistrement d'un rêve n'est pas testé sous charge** (voir ci-dessous).

## Le cas de l'enregistrement d'un rêve

C'est la vraie limite de l'application. Lors des essais réels, l'analyse a pris
environ 1 s et la création de l'image 5 à 7 s. Pendant ce temps, la requête
occupe un des 8 fils de Gunicorn. Une dizaine de rêves envoyés en même temps
suffisent donc à occuper tous les fils, et les autres pages doivent attendre.

Pistes d'amélioration, si l'application devait accueillir plus de monde :
- **faire tourner les étapes longues en tâche de fond**, avec une file de
  tâches comme Celery ou RQ : la requête répond tout de suite, et la page suit
  l'avancement ;
- **ajouter des fils ou des processus Gunicorn** sur une offre Render plus
  puissante ;
- **limiter le nombre d'enregistrements par utilisateur et par heure**, pour
  protéger le budget des API (voir le suivi des coûts dans l'admin).

## Refaire le test

```bash
pip install -r requirements-loadtest.txt

# 1. Données de test (choisir un mot de passe)
docker compose exec web python manage.py donnees_test_de_charge --mot-de-passe <mdp>

# 2. Serveur de production local, en http et sans clés d'API
docker compose run --rm -d --name charge-web -p 8001:8001 \
  -e DEBUG=False -e HTTPS_ONLY=False -e ALLOWED_HOSTS=localhost \
  -e GROQ_API_KEY= -e REPLICATE_API_TOKEN= -e CLOUDINARY_URL= \
  web sh -c "python manage.py collectstatic --noinput && gunicorn config.wsgi:application --workers 2 --threads 4 --keep-alive 5 --bind 0.0.0.0:8001"

# 3. Test (ici 100 utilisateurs pendant 1 minute)
LOADTEST_PASSWORD=<mdp> locust -f loadtests/locustfile.py --headless \
  --host http://localhost:8001 --users 100 --spawn-rate 10 --run-time 60s

# 4. Nettoyage
docker stop charge-web
docker compose exec web python manage.py donnees_test_de_charge --supprimer
```

Sans `--headless`, Locust ouvre une interface web sur http://localhost:8089,
avec des graphiques en direct.
