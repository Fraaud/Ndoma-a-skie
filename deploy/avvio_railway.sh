#!/usr/bin/env bash
# Avvio su Railway: un solo servizio che fa girare server web e bot insieme.
#
# Perche' insieme e non due servizi separati: su Railway un volume si monta
# su UN SOLO servizio, e il database e' un file SQLite su quel volume. Web e
# bot devono percio' condividere il container. Per la stessa ragione
# l'aggiornamento notturno lo fa il bot (AGGIORNA_DAL_BOT=1) invece di un cron.
set -uo pipefail
cd "$(dirname "$0")/.."

# Attiva il virtual environment se esiste (es. /venv o .venv)
if [ -d "/venv/bin" ]; then
    source /venv/bin/activate
elif [ -d ".venv/bin" ]; then
    source .venv/bin/activate
fi

echo "== Ndoma a skie' - avvio =="
echo "   cartella dati: ${DATA_DIR:-./data}"

# I file geografici viaggiano nel repository gia' ritagliati (3 MB): al primo
# avvio si copiano sul volume. Rigenerarli qui vorrebbe dire scaricare e
# analizzare un GeoJSON nazionale da un centinaio di MB, e su un container
# piccolo si rischia di esaurire la memoria proprio al primo deploy.
DATI="${DATA_DIR:-./data}"
for f in comuni.geojson eaws_micro_regions.geojson; do
  if [ ! -f "$DATI/$f" ] && [ -f "data/$f" ]; then
    echo "   copio $f sul volume"
    cp "data/$f" "$DATI/$f"
  fi
done
if [ ! -f "$DATI/comuni.geojson" ]; then
  echo "   file geografici assenti anche nel repository: provo a scaricarli"
  python scripts/setup_geo.py || echo "   ATTENZIONE: preparazione dati non riuscita"
fi

# Il catalogo si importa una volta sola, e non all'avvio: e' lento e non deve
# ritardare la risposta di Railway.  Prima volta, dalla shell del servizio:
#     python scripts/importa.py && python scripts/aggiorna.py

if [ -n "${TELEGRAM_BOT_TOKEN:-}" ]; then
  echo "   avvio il bot Telegram"
  python -m app.bot &
else
  echo "   TELEGRAM_BOT_TOKEN assente: parte solo il server web"
fi

# uvicorn in primo piano: e' il processo che Railway sorveglia, e deve
# ascoltare sulla porta che assegna lui.
echo "   server web sulla porta ${PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
