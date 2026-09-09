#!/usr/bin/env bash
# Prepara il progetto da zero. Si puo' rilanciare quante volte si vuole:
# salta i passaggi gia' fatti.
#
#   bash setup.sh
set -uo pipefail
cd "$(dirname "$0")"

verde() { printf "\033[92m%s\033[0m\n" "$*"; }
giallo() { printf "\033[93m%s\033[0m\n" "$*"; }
rosso() { printf "\033[91m%s\033[0m\n" "$*"; }
titolo() { printf "\n\033[1m== %s ==\033[0m\n" "$*"; }

# ---------------------------------------------------------------- 1. python
titolo "1/5  Ambiente Python"
if ! command -v python3 >/dev/null; then
  rosso "python3 non trovato. Installa Python 3.11+ (brew install python@3.12)."
  exit 1
fi
python3 --version

if [ ! -d venv ]; then
  echo "creo l'ambiente virtuale..."
  python3 -m venv venv || { rosso "creazione venv fallita"; exit 1; }
  verde "venv creato"
else
  verde "venv gia' presente"
fi
# shellcheck disable=SC1091
source venv/bin/activate

# ---------------------------------------------------------- 2. dipendenze
titolo "2/5  Dipendenze"
pip install -q --upgrade pip
if pip install -q -r requirements.txt; then
  verde "dipendenze installate"
else
  rosso "installazione fallita: guarda l'errore qui sopra"
  exit 1
fi

# ------------------------------------------------------------ 3. configurazione
titolo "3/5  Configurazione"
if [ ! -f .env ]; then
  cp .env.example .env
  giallo ".env creato da .env.example: apri il file e metti il token del bot"
else
  verde ".env presente"
fi
if grep -q "^TELEGRAM_BOT_TOKEN=$" .env 2>/dev/null; then
  giallo "TELEGRAM_BOT_TOKEN e' ancora vuoto."
  giallo "Scrivi a @BotFather su Telegram, fai /newbot e incolla il token in .env"
fi

# --------------------------------------------------------------- 4. test
titolo "4/5  Test (non serve rete)"
if python -m pytest tests/ -q 2>&1 | tail -3; then
  verde "test ok"
else
  rosso "qualche test fallisce: mandami l'output"
fi

# ---------------------------------------------------------- 5. fonti dati
titolo "5/5  Fonti dati esterne"
python scripts/check_fonti.py

cat <<'FINE'

------------------------------------------------------------------
Prossimi passi, in ordine:

  source venv/bin/activate

  python scripts/setup_geo.py     confini comunali + micro-regioni valanghe
  python scripts/importa.py       catalogo gite dalle fonti aperte
  python scripts/aggiorna.py      meteo e bollettini nella cache

  bash avvia.sh                   server + bot insieme

Per vedere subito l'interfaccia senza scaricare niente:
  python scripts/seed_demo.py && bash avvia.sh
------------------------------------------------------------------
FINE
