# synthetiseur-de-reves
Application : raconte ton rêve, l’IA le transcrit, l’analyse et l’illustre

## Qualité du code

Le projet utilise [ruff](https://docs.astral.sh/ruff/) (configuré dans `pyproject.toml`) et un hook pre-commit qui bloque tout commit non conforme.

```bash
pip install -r requirements-dev.txt
pre-commit install
```

Lancer les vérifications à la main :

```bash
pre-commit run --all-files
```
