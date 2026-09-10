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

# Il controllo che conta di piu': la cartella dati e' un volume, o e' dentro
# l'immagine? Un volume montato sta su un dispositivo DIVERSO da quello del
# codice. Se sono lo stesso, a ogni deploy si perdono iscritti e catalogo -
# e l'app riparte perfettamente, solo vuota, senza un errore da nessuna
# parte. Meglio una riga urlata nei log che una domanda "perche' devo
# rimettere tutto?".
if [ "$(stat -c %d "$DATI" 2>/dev/null)" = "$(stat -c %d . 2>/dev/null)" ]; then
  echo "   !!  ATTENZIONE: $DATI NON e' un volume, sta dentro l'immagine."
  echo "   !!  A ogni deploy si perdono utenti, preferenze e catalogo."
  echo "   !!  Su Railway: Settings -> Volumes, punto di mount $DATI."
else
  echo "   volume: ok, i dati sopravvivono ai deploy"
fi

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

# Conta le righe di una tabella. Sembra banale e non lo e': all'avvio i
# moduli di python possono stampare avvisi (un DATABASE_URL da correggere,
# una colonna aggiunta allo schema), e se finiscono nello stesso flusso del
# numero il risultato diventa "ATTENZIONE: ...\n0" - che nel confronto di
# bash fa "integer expression expected" e manda il controllo a vuoto in
# silenzio. E' successo davvero: tre passaggi saltati e un'app vuota senza
# spiegazione. Doppia difesa: gli avvisi vanno su stderr (vedi
# app/config.py), e qui si tiene solo l'ultima riga e solo le cifre.
conta() {
  local n
  n=$(python - "$1" 2>/dev/null <<'CONTA' | tail -n 1 | tr -cd '0-9'
import sys, datetime as dt
from app.db import SessionLocal, init_db
from app.models import Comune, Condizioni, Gita, Posto, Traccia
init_db()
db = SessionLocal()
quale = sys.argv[1]
if quale == "gite":
    print(db.query(Gita).count())
elif quale == "comuni":
    print(db.query(Comune).count())
elif quale == "posti":
    print(db.query(Posto).count())
elif quale == "tracce":
    print(db.query(Traccia).count())
elif quale == "simulazione":
    from app import simulazione
    print(1 if simulazione.caricata(db) else 0)
else:
    print(db.query(Condizioni).filter(Condizioni.giorno >= dt.date.today()).count())
db.close()
CONTA
)
  echo "${n:-0}"
}

# L'elenco dei comuni sta in archivio, non nel file: il geojson serve alla
# geometria (che paesi attraversa un percorso), le righe servono alla ricerca
# del comune di partenza - il campo senza il quale non si pubblica un'uscita.
# Copiare il file non basta, vanno scritte anche quelle. Sono pochi secondi.
if [ "$(conta comuni)" -lt 100 ]; then
  echo "   scrivo l'elenco dei comuni in archivio"
  python scripts/setup_geo.py --solo-archivio || echo "   ATTENZIONE: elenco comuni non scritto"
fi

# I codici ISTAT devono stare tutti nella stessa forma (sei cifre): per un
# periodo l'indice spaziale ne scriveva una versione e la tabella dei comuni
# un'altra, e la regola "il passeggero e' sulla strada di chi guida" non
# poteva scattare. E' un no-op dopo la prima volta.
python scripts/ripara_istat.py || echo "   ATTENZIONE: riparazione ISTAT non riuscita"

# Due controlli separati, non uno solo. Il catalogo e le condizioni meteo si
# riempiono con due comandi diversi, e ognuno puo' fallire per conto suo: la
# prima volta l'import si e' fermato a meta' e aggiorna.py, che veniva dopo,
# non e' mai partito - risultato, una vista Weekend vuota senza spiegazione.
# Chiedendo a ognuno se il SUO lavoro e' fatto, un avvio successivo rimedia
# da solo a quello che manca.
gite=$(conta gite)
condizioni=$(conta condizioni)
echo "   catalogo: $gite itinerari, $condizioni giornate di condizioni, $(conta comuni) comuni"

# Il catalogo si importa una volta sola. La soglia non e' zero: se un
# tentativo si interrompe a meta' (rete, memoria, un deploy che riparte) il
# riavvio successivo lo rifa' invece di restare con mezzo catalogo per
# sempre. Reimportare non duplica niente: ogni itinerario si riconosce da
# fonte + identificativo.
lavoro=""
if [ "$gite" -lt 300 ]; then
  echo "   catalogo incompleto: importo in sottofondo"
  lavoro="python scripts/importa.py"
fi

# Parcheggi, ripari e piole: si scaricano una volta e non si toccano piu'
# (un parcheggio non si sposta). Servono anche alla schermata Emergenza, che
# tiene i ripari da parte per quando non c'e' campo, quindi vale la pena
# averli anche se nessuno ha ancora aperto una scheda.
if [ "$gite" -ge 300 ] && [ "$(conta posti)" -eq 0 ]; then
  echo "   nessun parcheggio in archivio: li scarico da OpenStreetMap"
  lavoro="${lavoro:+$lavoro && }python scripts/importa_posti.py"
fi

# Le tracce: si scaricano una volta e poi restano. Sono il dato che l'app
# non aveva e che tutti chiedono, e costano una chiamata per gita alla
# fonte - sei minuti, in sottofondo. Le quote lungo la traccia (il profilo
# altimetrico) vanno con --quote e passano dalla chiave ORS, che ha una
# quota giornaliera: se si interrompe, il riavvio dopo riprende da dove
# era.
if [ "$gite" -ge 300 ] && [ "$(conta tracce)" -eq 0 ]; then
  echo "   nessuna traccia in archivio: le scarico dalla fonte"
  lavoro="${lavoro:+$lavoro && }python scripts/importa_tracce.py"
  if [ -n "${ORS_API_KEY:-}" ]; then
    lavoro="$lavoro && python scripts/importa_tracce.py --quote"
  fi
fi

# Meteo e bollettini si rifanno comunque ogni notte: qui servono solo se non
# c'e' proprio niente, cioe' al primo avvio o dopo un import interrotto.
#
# Il secondo caso e' piu' sottile: la simulazione appena accesa. In archivio
# le condizioni CI SONO (sono quelle vere), quindi il controllo qui sopra
# risponderebbe "tutto a posto" e la simulazione comparirebbe solo dopo
# l'aggiornamento notturno - cioe' domani. Chi ha appena impostato la
# variabile si aspetta di vederla adesso, e ha ragione.
if [ "$condizioni" -eq 0 ]; then
  echo "   nessuna condizione in archivio: scarico meteo e bollettini"
  lavoro="${lavoro:+$lavoro && }python scripts/aggiorna.py"
elif [ -n "${SIMULAZIONE_INVERNO:-}" ] && [ "$(conta simulazione)" -eq 0 ]; then
  echo "   simulazione accesa ma in archivio ci sono i dati veri: la carico"
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
