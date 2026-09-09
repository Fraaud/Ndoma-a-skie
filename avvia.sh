#!/usr/bin/env bash
# Avvia insieme il server web e il bot Telegram, e li ferma insieme con Ctrl+C.
#
#   bash avvia.sh          server + bot
#   bash avvia.sh --solo-web   solo il server (utile per provare l'interfaccia
#                              dal browser senza avere ancora il token del bot)
set -uo pipefail
cd "$(dirname "$0")"

verde() { printf "\033[92m%s\033[0m\n" "$*"; }
giallo() { printf "\033[93m%s\033[0m\n" "$*"; }

if [ ! -d venv ]; then
  giallo "Manca l'ambiente virtuale: lancia prima  bash setup.sh"
  exit 1
fi
# shellcheck disable=SC1091
source venv/bin/activate

PID_WEB=""
PID_BOT=""
chiudi() {
  echo
  echo "chiudo..."
  [ -n "$PID_WEB" ] && kill "$PID_WEB" 2>/dev/null
  [ -n "$PID_BOT" ] && kill "$PID_BOT" 2>/dev/null
  wait 2>/dev/null
  exit 0
}
trap chiudi INT TERM

verde "server web  -> http://localhost:8000"
# Sorveglia SOLO app/: test, script, importatori e venv non fanno parte del
# server, e se la cartella e' sincronizzata (iCloud, Dropbox) ogni ritocco del
# servizio di sync farebbe ripartire uvicorn a raffica.
uvicorn app.main:app --reload --reload-dir app --port 8000 \
        --reload-exclude "* 2.py" --reload-exclude "*.db*" &
PID_WEB=$!

if [ "${1:-}" != "--solo-web" ]; then
  # il bot parte solo se c'e' il token, altrimenti uscirebbe subito con errore
  if grep -qE "^TELEGRAM_BOT_TOKEN=.+" .env 2>/dev/null; then
    sleep 2
    verde "bot Telegram -> avviato"
    python -m app.bot &
    PID_BOT=$!
  else
    giallo "bot non avviato: TELEGRAM_BOT_TOKEN e' vuoto in .env"
    giallo "(il server web funziona lo stesso, apri http://localhost:8000)"
  fi
fi

cat <<'NOTA'

Per far vedere l'app dentro Telegram serve un indirizzo https: in un altro
terminale lancia

  cloudflared tunnel --url http://localhost:8000

poi copia l'URL che ti stampa in WEBAPP_URL dentro .env e riavvia questo script.

Ctrl+C per fermare tutto.
NOTA

wait
