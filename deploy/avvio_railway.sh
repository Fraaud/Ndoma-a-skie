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

# L'elenco dei comuni sta in archivio, non nel file: il geojson serve alla
# geometria (che paesi attraversa un percorso), le righe servono alla ricerca
# del comune di partenza. Copiare il file non basta, vanno scritte anche
# quelle, se non ci sono gia'. Sono pochi secondi.
if [ "$(python -c "
from app.db import SessionLocal, init_db
from app.models import Comune
init_db()
db = SessionLocal(); print(db.query(Comune).count()); db.close()
" 2>/dev/null || echo 0)" -lt 100 ]; then
  echo "   scrivo l'elenco dei comuni in archivio"
  python scripts/setup_geo.py --solo-archivio || echo "   ATTENZIONE: elenco comuni non scritto"
fi

# Due controlli separati, non uno solo. Il catalogo e le condizioni meteo si
# riempiono con due comandi diversi, e ognuno puo' fallire per conto suo: la
# prima volta l'import si e' fermato a meta' e aggiorna.py, che veniva dopo,
# non e' mai partito - risultato, una vista Weekend vuota senza spiegazione.
# Chiedendo a ognuno se il SUO lavoro e' fatto, un avvio successivo rimedia
# da solo a quello che manca.
conta() {
  python - "$1" 2>/dev/null <<'CONTA' || echo 0
import sys, datetime as dt
from app.db import SessionLocal, init_db
from app.models import Gita, Condizioni
init_db()
db = SessionLocal()
if sys.argv[1] == "gite":
    print(db.query(Gita).count())
else:
    print(db.query(Condizioni).filter(Condizioni.giorno >= dt.date.today()).count())
db.close()
CONTA
}

gite=$(conta gite)
condizioni=$(conta condizioni)
echo "   catalogo: ${gite:-0} itinerari, ${condizioni:-0} giornate di condizioni"

# Il catalogo si importa una volta sola. La soglia non e' zero: se un
# tentativo si interrompe a meta' (rete, memoria, un deploy che riparte) il
# riavvio successivo lo rifa' invece di restare con mezzo catalogo per
# sempre. Reimportare non duplica niente: ogni itinerario si riconosce da
# fonte + identificativo.
lavoro=""
if [ "${gite:-0}" -lt 300 ]; then
  echo "   catalogo incompleto: importo in sottofondo"
  lavoro="python scripts/importa.py"
fi

# Meteo e bollettini si rifanno comunque ogni notte: qui servono solo se non
# c'e' proprio niente, cioe' al primo avvio o dopo un import interrotto.
if [ "${condizioni:-0}" -eq 0 ]; then
  echo "   nessuna condizione in archivio: scarico meteo e bollettini"
  lavoro="${lavoro:+$lavoro && }python scripts/aggiorna.py"
fi

# In sottofondo, perche' ci vogliono minuti e Railway considera fallito un
# deploy che non apre subito la porta. Il log sta sul volume, cosi' lo si
# rilegge dalla shell anche dopo:   tail -f $DATA_DIR/primo_avvio.log
if [ -n "$lavoro" ]; then
  (
    echo "== avvio del $(date) =="
    eval "$lavoro"
    echo "== finito, esito $? =="
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
