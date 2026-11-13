#!/usr/bin/env bash
#
# Installation du Synthétiseur de rêves.
#
#   ./install.sh          installation locale (environnement virtuel Python)
#   ./install.sh docker   installation avec Docker (PostgreSQL inclus)
#
# Le script s'arrête à la première erreur. Il peut être relancé sans risque :
# ce qui existe déjà (.venv, .env) est conservé.

set -euo pipefail

cd "$(dirname "$0")"

MODE="${1:-venv}"
PYTHON="${PYTHON:-python3.12}"

step() { printf '\n\033[1;35m==> %s\033[0m\n' "$1"; }
fail() { printf '\n\033[1;31mErreur : %s\033[0m\n' "$1" >&2; exit 1; }

# --- Fichier .env ---------------------------------------------------------------
# Copie .env.example et génère une SECRET_KEY aléatoire. Les clés d'API restent
# vides : l'application fonctionne, mais sans transcription, analyse ni image
# tant qu'elles ne sont pas renseignées.
create_env() {
  step "Fichier de configuration .env"
  if [ -f .env ]; then
    echo ".env existe déjà : il est conservé."
    return
  fi
  cp .env.example .env
  "$1" - <<'PY'
import secrets
from pathlib import Path

env = Path(".env")
key = secrets.token_urlsafe(50)
env.write_text(env.read_text().replace("SECRET_KEY=change-me", f"SECRET_KEY={key}"))
PY
  echo ".env créé, avec une SECRET_KEY aléatoire."
}

install_venv() {
  step "Vérification de Python 3.12"
  command -v "$PYTHON" >/dev/null 2>&1 \
    || fail "$PYTHON est introuvable. Installez Python 3.12, ou indiquez son chemin : PYTHON=/chemin/python3.12 ./install.sh"
  "$PYTHON" -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))' \
    || fail "$PYTHON n'est pas Python 3.12."
  "$PYTHON" --version

  step "Environnement virtuel .venv"
  if [ ! -d .venv ]; then
    "$PYTHON" -m venv .venv
    echo ".venv créé."
  else
    echo ".venv existe déjà : il est réutilisé."
  fi
  # shellcheck disable=SC1091
  source .venv/bin/activate

  step "Installation des dépendances"
  python -m pip install --quiet --upgrade pip
  python -m pip install --quiet -r requirements-dev.txt
  echo "Dépendances installées."

  create_env python

  step "Base de données (SQLite par défaut)"
  python manage.py migrate --noinput

  step "Vérification : lancement des tests"
  python -m pytest -q

  step "Installation terminée"
  cat <<'TXT'
Prochaines étapes :
  1. Renseignez vos clés d'API dans .env (voir le README) ;
  2. source .venv/bin/activate
  3. python manage.py createsuperuser   (compte pour l'admin)
  4. python manage.py runserver         puis ouvrez http://localhost:8000
TXT
}

install_docker() {
  step "Vérification de Docker"
  command -v docker >/dev/null 2>&1 || fail "Docker est introuvable. Installez Docker Desktop."
  docker info >/dev/null 2>&1 || fail "Docker ne répond pas. Lancez Docker Desktop, puis relancez le script."

  create_env python3

  step "Construction et démarrage (application + PostgreSQL)"
  docker compose up -d --build

  step "Base de données PostgreSQL"
  docker compose exec -T web python manage.py migrate --noinput

  step "Vérification : lancement des tests"
  docker compose exec -T web python manage.py test

  step "Installation terminée"
  cat <<'TXT'
L'application tourne sur http://localhost:8000

Prochaines étapes :
  1. Renseignez vos clés d'API dans .env (voir le README), puis :
     docker compose up -d --force-recreate web
  2. docker compose exec web python manage.py createsuperuser   (compte pour l'admin)
TXT
}

case "$MODE" in
  venv) install_venv ;;
  docker) install_docker ;;
  *) fail "mode inconnu « $MODE ». Utilisez : ./install.sh   ou   ./install.sh docker" ;;
esac
