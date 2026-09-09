#!/usr/bin/env bash
# Avvia insieme il server web e il bot Telegram, e li ferma insieme con Ctrl+C.
#
#   bash avvia.sh              server + bot
#   bash avvia.sh --solo-web   solo il server, per provare l'interfaccia dal
#                              browser senza avere ancora il token del bot
set -uo pipefail
cd "$(dirname "$0")"

verde() { printf "\033[92m%s\033[0m\n" "$*"; }
giallo() { printf "\033[93m%s\033[0m\n" "$*"; }
grigio() { printf "\033[90m%s\033[0m\n" "$*"; }

if [ ! -d venv ]; then
  giallo "Manca l'ambiente virtuale: lancia prima  bash setup.sh"
  exit 1
fi
# shellcheck disable=SC1091
source venv/bin/activate

PID_SERVER=""
PID_BOT=""
chiudi() {
  echo
  echo "chiudo..."
  [ -n "$PID_SERVER" ] && kill "$PID_SERVER" 2>/dev/null
  [ -n "$PID_BOT" ] && kill "$PID_BOT" 2>/dev/null
  wait 2>/dev/null
  exit 0
}
trap chiudi INT TERM

INDIRIZZO=$(grep -E "^WEBAPP_URL=" .env 2>/dev/null | cut -d= -f2- || true)

printf "\n\033[1mNDOMA A SKIÉ\033[0m\n"
verde "  server      http://localhost:8000"
[ -n "$INDIRIZZO" ] && grigio "  mini app    $INDIRIZZO"
grigio "  stato       http://localhost:8000/api/salute"
echo

# Sorveglia SOLO app/: test, script, importatori e venv non fanno parte del
# server, e se la cartella e' sincronizzata (iCloud, Dropbox) ogni ritocco del
# servizio di sync farebbe ripartire uvicorn a raffica.
uvicorn app.main:app --reload --reload-dir app --port 8000 \
        --reload-exclude "* 2.py" --reload-exclude "*.db*" &
PID_SERVER=$!

if [ "${1:-}" != "--solo-web" ]; then
  # il bot parte solo se c'e' il token, altrimenti uscirebbe subito con errore
  if grep -qE "^TELEGRAM_BOT_TOKEN=.+" .env 2>/dev/null; then
    sleep 2
    verde "  bot Telegram avviato"
    python -m app.bot &
    PID_BOT=$!
  else
    giallo "  bot non avviato: TELEGRAM_BOT_TOKEN e' vuoto in .env"
    giallo "  (il server funziona lo stesso, apri http://localhost:8000)"
  fi
fi

cat <<'NOTA'

Telegram accetta le mini app solo in https: in un altro terminale lancia

  cloudflared tunnel --url http://localhost:8000

poi metti l'indirizzo che stampa in WEBAPP_URL dentro .env e riavvia questo
script. Non riavviare cloudflared se non serve: ogni suo riavvio cambia
l'indirizzo e obbliga a rifare /start su Telegram.

Le righe che seguono sono i registri di uvicorn e della libreria Telegram,
e parlano inglese: "POST /api/uscite 200 OK" vuol dire che ha funzionato.

Ctrl+C per fermare tutto.
NOTA

wait
