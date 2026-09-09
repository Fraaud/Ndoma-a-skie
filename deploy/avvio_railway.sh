#!/usr/bin/env bash
# Avvio su Railway: un solo servizio che fa girare server web e bot insieme.
#
# Perche' insieme e non due servizi separati: su Railway un volume si monta
# su UN SOLO servizio, e il database e' un file SQLite su quel volume. Web e
# bot devono percio' condividere il container. Per la stessa ragione
# l'aggiornamento notturno lo fa il bot (AGGIORNA_DAL_BOT=1) invece di un cron.
set -uo pipefail
cd "$(dirname "$0")/.."

DATI="${DATA_DIR:-./data}"
mkdir -p "$DATI"

echo "== Ndoma a skie' - avvio =="
echo "   cartella dati: $DATI"

# I file geografici viaggiano nel repository gia' ritagliati (3 MB): al primo
# avvio si copiano sul volume. Rigenerarli qui vorrebbe dire scaricare e
# analizzare un GeoJSON nazionale da un centinaio di MB, e su un container
# piccolo si rischia di esaurire la memoria proprio al primo deploy.
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

# Quante gite ci sono gia' in archivio. Se il database non esiste ancora,
# init_db lo crea vuoto e la risposta e' zero.
gite=$(python - <<'PY' 2>/dev/null || echo 0
from app.db import SessionLocal, init_db
from app.models import Gita
init_db()
db = SessionLocal()
print(db.query(Gita).count())
db.close()
PY
)
echo "   catalogo: ${gite:-0} itinerari"

# Primo avvio: si importa il catalogo e si scaricano meteo e bollettini.
# In sottofondo, perche' ci vogliono minuti e Railway considera fallito un
# deploy che non apre la porta subito. Il log finisce sul volume, cosi' lo si
# rilegge dalla shell anche dopo:   tail -f $DATA_DIR/primo_avvio.log
# La soglia non e' zero ma cinquanta: se un primo tentativo si e' interrotto
# a meta' (rete, memoria) il riavvio successivo lo rifa' invece di restare
# con mezzo catalogo per sempre. Importare due volte non duplica nulla:
# gli itinerari si riconoscono dalla sorgente e dal loro identificativo.
if [ "${gite:-0}" -lt 50 ]; then
  echo "   catalogo da riempire: importo in sottofondo (qualche minuto)"
  (
    python scripts/importa.py && python scripts/aggiorna.py
    echo "== primo avvio completato =="
  ) >> "$DATI/primo_avvio.log" 2>&1 &
fi

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
