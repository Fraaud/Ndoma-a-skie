# NDOMA A SKIÉ

Mini app Telegram per lo scialpinismo del Cuneese e del Mercantour.

1. **Scheda gita** — per ogni itinerario: meteo, qualita' della neve prevista
   e il pericolo valanghe ufficiale, riportati senza interpretazioni.
2. **Passaggi in auto** — chi offre posti, chi cerca un passaggio, chi cerca
   compagnia. Il match tiene conto dei **comuni che l'auto attraversa**, non
   della distanza in linea d'aria.

> ### Avvertenza
>
> **Questa applicazione non valuta la sicurezza di un itinerario e non
> sostituisce il bollettino valanghe ufficiale.**
>
> Il grado di pericolo mostrato e' quello emesso dagli enti competenti,
> semplicemente riportato: non viene calcolato ne' interpretato. Della neve
> l'app dice solo **quanta ne e' caduta**, un dato misurato, e ricorda che i
> giorni dopo una nevicata sono quelli a pericolo piu' alto.
>
> Prima di ogni uscita si legge il bollettino integrale dell'ente emittente.

---

## Da dove vengono i dati

| Cosa | Fonte | Licenza / accesso |
|---|---|---|
| Itinerari | [Camptocamp.org](https://www.camptocamp.org/api/) | CC-BY-SA, API pubblica |
| Itinerari versante francese | [Skitour.fr](https://skitour.fr/api/) | CC-BY-SA 4.0, chiave gratuita |
| Itinerari e parcheggi | OpenStreetMap (Overpass) | ODbL |
| Meteo | [Open-Meteo](https://open-meteo.com/) | gratuito non commerciale, senza chiave |
| Micro-regioni valanghe | [regions.avalanches.org](https://regions.avalanches.org/) | open data |
| Bollettini valanghe | [archivio EAWS](https://static.avalanche.report/eaws_bulletins/), [AINEVA](https://bollettini.aineva.it/) | ufficiali (Piemonte: ARPA Piemonte) |
| Confini comunali | ISTAT via [OnData](https://www.confini-amministrativi.it/) | open data |
| Percorsi auto | [openrouteservice](https://openrouteservice.org/) | chiave gratuita (facoltativa) |

Del catalogo servono otto campi: nome, coordinate del parcheggio, quote,
dislivello, esposizione, difficolta'. Nessun testo di relazione: quella si
legge sulla fonte, che ogni scheda linka. Non si copiano contenuti da siti
che non li rilasciano con licenza aperta, e nemmeno loro riassunti.

---

## Installazione

```bash
bash setup.sh          # ambiente, dipendenze, .env, test, diagnosi delle fonti
```

Poi il token del bot da [@BotFather](https://t.me/BotFather) (`/newbot`) in
`.env` come `TELEGRAM_BOT_TOKEN`, e i dati:

```bash
source venv/bin/activate
python scripts/setup_geo.py            # confini comunali + micro-regioni valanghe
python scripts/importa.py              # catalogo dalle fonti aperte
python scripts/aggiorna.py             # meteo, bollettini, punteggi
```

`setup_geo.py` va **prima** dell'import: senza, le gite finiscono senza comune
e senza zona valanghe. `check_fonti.py` dice in trenta secondi quali endpoint
rispondono e quali chiavi mancano; se qualcosa e' rosso, gli URL stanno tutti
in `app/config.py`.

> Fuori stagione i bollettini valanghe non esistono: in Piemonte l'emissione
> e' sospesa d'estate e riprende a inizio inverno.

## Avvio in locale

```bash
bash avvia.sh          # server web + bot
```

Telegram pretende **https** per le mini app, quindi in locale serve un tunnel,
in un secondo terminale:

```bash
cloudflared tunnel --url http://localhost:8000
```

L'indirizzo che stampa va in `.env` come `WEBAPP_URL`, poi si riavvia
`avvia.sh` e su Telegram si fa `/start`. Il bottone che apre la mini app
contiene l'indirizzo al suo interno: se cambia il tunnel, il bot va riavviato
e i vecchi messaggi `/start` restano inservibili.

**Non riavviare cloudflared** se non necessario: sopravvive ai riavvii del
server, e ogni suo riavvio cambia l'indirizzo.

Stato del sistema: <http://localhost:8000/api/salute>

---

## Deploy su Railway

Railway costruisce dal repository: a ogni `git push` ridistribuisce da solo.

**Un vincolo decide l'architettura**: su Railway un volume si monta su un
solo servizio, e il database e' un file SQLite su quel volume. Quindi server
web e bot girano **nello stesso servizio** (`deploy/avvio_railway.sh` li avvia
entrambi) e l'aggiornamento notturno lo fa il bot invece di un cron separato.
Niente Postgres, niente servizi aggiuntivi.

**1. Crea il progetto** su railway.app: *New Project* -> *Deploy from GitHub
repo* -> questo repository. C'e' un `Dockerfile`: Railway lo usa e basta,
non serve configurare niente. L'immagine installa le dipendenze di sistema
(niente virtualenv), cosi' `python scripts/...` funziona anche dalla shell
del servizio.

**2. Aggiungi il volume**, in *Settings -> Volumes* (o ⌘K -> *Volume*), con
punto di mount `/data`. E' l'unica cosa che sopravvive ai riavvii: senza,
a ogni deploy perdi database, catalogo e utenti.

**3. Variabili d'ambiente**, in *Variables*:

```
TELEGRAM_BOT_TOKEN=quello di BotFather
DATA_DIR=/data
AGGIORNA_DAL_BOT=1                          # aggiornamento notturno alle 4:00
BBOX=6.55,44.00,7.95,44.75
HTTP_USER_AGENT=ndoma-a-skie/1.0 (contatto: tua@email.it)
WEBAPP_URL=                                 # si compila al passo 4
SIMULAZIONE_INVERNO=2026-02-14              # dati di prova fuori stagione
```

**Non** impostare `DATABASE_URL`: lasciandolo vuoto il database finisce da
solo in `$DATA_DIR/ndoma.db`, cioe' sul volume. Il `.env` locale contiene un
percorso *relativo*, che dentro un container punta nell'immagine: a ogni
deploy si perdono iscritti, preferenze e catalogo, e l'app riparte
perfettamente, solo vuota. Se proprio lo imposti, servono **quattro** barre:
`sqlite:////data/ndoma.db`.

Un percorso relativo con `DATA_DIR` impostato viene comunque dirottato sul
volume, con un avviso nei log - ma non e' una scusa per scriverlo male. Il
controllo da fare dopo ogni deploy e' la prima riga dei log:

```
archivio: /data/ndoma.db - sul volume, 27.5 MB
volume: ok, i dati sopravvivono ai deploy
```

Se invece dice `DENTRO L'IMMAGINE (si perde!)`, il volume non e' montato:
`/api/salute` riporta la stessa cosa in `archivio.persistente`.

**4. Genera il dominio**, in *Settings -> Networking -> Generate Domain*.
Copia l'indirizzo in `WEBAPP_URL` e ridistribuisci: il bot scrive
quell'indirizzo dentro il bottone che apre la mini app, quindi finche' e'
vuoto il bottone non funziona. Railway mostra il dominio senza `https://`
e va bene lo stesso, ci pensa il programma ad aggiungerlo (Telegram accetta
solo link https, e senza schema rifiutava il bottone).

**5. Il catalogo si riempie da solo.** Al primo avvio, se in archivio ci sono
meno di cinquanta itinerari, `deploy/avvio_railway.sh` lancia in sottofondo:

```bash
python scripts/importa.py && python scripts/aggiorna.py
```

In sottofondo perche' ci vogliono alcuni minuti e Railway considera fallito
un deploy che non apre subito la porta. Per seguirlo, dalla shell del
servizio:

```bash
tail -f /data/primo_avvio.log
```

Nel frattempo il sito risponde gia', solo con il catalogo vuoto. Reimportare
non duplica nulla: ogni itinerario si riconosce da fonte + identificativo.

I confini comunali e le micro-regioni valanghe viaggiano nel repository gia'
ritagliati sul BBOX (3 MB) e al primo avvio vengono copiati sul volume:
rigenerarli richiederebbe di scaricare e analizzare un GeoJSON nazionale da
un centinaio di MB, e su un container piccolo si finisce la memoria.

**6. Backup.** Il database e' un file solo, ma con WAL attivo non si copia con
`cp`:

```bash
sqlite3 /data/ndoma.db ".backup '/data/backup.db'"
```

Poi scaricalo dalla shell di Railway. Vale la pena farlo prima di ogni
modifica importante allo schema.

### Se un domani servisse separare i servizi

Con molti piu' utenti, web e bot possono stare su servizi distinti: in quel
caso il database deve diventare Postgres (Railway lo offre come componente),
perche' due servizi non possono condividere lo stesso volume. Cambia solo
`DATABASE_URL` e si aggiunge `psycopg[binary]` alle dipendenze: il codice usa
SQLAlchemy e non ha query specifiche di SQLite.

---

## Com'e' fatto

```
app/
  main.py          API FastAPI + serve la mini app
  bot.py           bot Telegram: comandi, notifiche, lavori periodici
  notifiche.py     invio dei match e recupero di quelli non riusciti
  telegram_ui.py   menzioni e bottoni (funzionano anche senza username)
  aggiornamento.py meteo, bollettini e punteggi: lo stesso codice per cron e bot
  models.py        Gita, Utente, Uscita, Match, Percorso, Comune, Condizioni
  auth.py          verifica HMAC dell'initData Telegram (unico punto di sicurezza)
  geo.py           indici spaziali: comune di un punto, comuni attraversati
  schede.py        composizione della scheda gita
  services/        meteo, neve, valanghe, routing, match
  static/          mini app (html + css + un solo js)
importers/         camptocamp, skitour, osm
scripts/           check_fonti, setup_geo, importa, aggiorna,
                   prova_match, prova_inverno, seed_demo
deploy/            avvio_railway.sh
```

Gli script di diagnosi valgono i due minuti che costa impararli:
`check_fonti.py` dice quali sorgenti esterne rispondono, `prova_match.py`
dice perche' un match non e' scattato, `prova_inverno.py` carica una giornata
d'inverno vera per provare l'app fuori stagione.

### La neve caduta

L'app riporta **quanti centimetri sono caduti nelle ultime 72 ore** alla quota
dell'attacco, quanti nelle ultime 24, e quante ore sono passate dall'ultima
nevicata. Sono quantita' misurate dal modello meteo, riportate come si
riporterebbe una temperatura.

**Non si calcola nessun punteggio di qualita' della neve.** C'era, andava da 0
a 5 e pesava vento, temperatura e crosta: e' stato tolto. Un indice inventato
da noi finisce per essere letto come un giudizio, e ordinare le gite per
"quanto sara' bella" spinge verso le giornate con piu' neve fresca, che sono
anche quelle con il pericolo piu' alto. Il fatto si riporta, il giudizio no.

**Quando c'e' neve fresca, l'avvertenza accompagna sempre il dato**: i giorni
dopo una nevicata sono quelli in cui il pericolo di valanghe e' piu' alto, la
neve non si e' assestata e il vento puo' averla accumulata in lastroni. E'
un richiamo generale, quello che sta in apertura di qualunque manuale, non una
valutazione dell'itinerario. Un test fallisce se sparisce.

### Il bollettino valanghe

**L'app riporta il bollettino ufficiale. Non lo interpreta, in nessuna forma.**

Regole in `app/services/valanghe.py`, non negoziabili:

1. Nessun grado di pericolo calcolato da noi: solo quello emesso dall'ente.
2. Nessun semaforo verde, nessun "si puo' andare".
3. Nessun incrocio fra il bollettino e i dati della gita. In particolare
   **nessuna evidenziazione di quali problemi "riguardano" un itinerario**:
   scegliere cosa mettere in risalto e' gia' interpretare, e implica che il
   resto non ti riguardi. Per giunta l'esposizione delle gite arriva dalle
   fonti spesso incompleta, quindi quel filtro sarebbe anche inaffidabile.
4. Sempre visibili: ente emittente, ora di emissione, tutti i problemi
   segnalati con esposizioni e quote, link al bollettino integrale.

Centimetri e grado ufficiale stanno **accanto** nella lista, senza che l'app
dica come metterli in relazione: quel giudizio e' di chi va in montagna, sul
bollettino integrale e sul terreno.

### Provarla fuori stagione

Da maggio a novembre non c'e' neve e il bollettino piemontese e' sospeso:
senza dati l'app sembra rotta. `SIMULAZIONE_INVERNO=2026-02-14` fa girare
tutto su una giornata d'inverno **realmente accaduta** - meteo storico da
Open-Meteo, bollettino dall'archivio EAWS - spostando soltanto le etichette
temporali sul prossimo weekend. I valori restano quelli veri: se il 14
febbraio erano caduti 40 cm, in app si leggono 40 cm.

Un grado di pericolo mostrato senza contesto e' pero' indistinguibile da
quello di oggi, e qualcuno potrebbe usarlo per decidere una gita. Per questo:

- l'ente emittente diventa `SIMULAZIONE - bollettino del <data>`, visibile
  in ogni scheda;
- l'app mostra una **fascia fissa e non chiudibile** in cima a ogni
  schermata, che nomina la data vera dei dati;
- del contenuto del bollettino non si tocca una parola: cambia l'etichetta
  di chi lo ha emesso, non cio' che dice.

Finche' la variabile c'e', l'aggiornamento notturno ricarica la simulazione
invece dei dati di oggi - altrimenti alle 4:00 la cancellerebbe e la mattina
l'app tornerebbe vuota. Per tornare alla realta': si toglie la variabile e si
rilancia `scripts/aggiorna.py`. `scripts/prova_inverno.py` serve solo per
provare un'altra data al volo, o per ripulire (`--pulisci`).

### Il match

| Criterio | Punti |
|---|---|
| il comune di chi cerca e' **sul percorso** di chi guida | +4 |
| entro 8 km dal percorso | +2,5 |
| stessa gita | +3 |
| stessa data | +3 (entro flessibilita': +2) |
| stessa zona / valle | +1,5 |
| orari compatibili | +0,5 |

Soglia 5. I percorsi si calcolano una volta per coppia (comune, gita) e restano
in cache.

**Mai la distanza in linea d'aria fra due attacchi**: in montagna dodici
chilometri in linea d'aria possono essere due valli diverse e novanta
chilometri di strada. Gite diverse combaciano solo se stessa valle, stesso
comune, o una sull'itinerario stradale dell'altra. Un test presidia la regola.

**Un codice ISTAT, un formato solo.** Il GeoJSON dei comuni porta lo stesso
codice come `"004078"` e come `4078`: l'indice spaziale leggeva il numero, la
tabella dei comuni la stringa, e confrontando stringhe non erano mai uguali.
Risultato: la regola che vale piu' di tutte, "il passeggero e' sulla strada di
chi guida", non poteva scattare mai, e i paesi attraversati comparivano come
numeri invece che come nomi. Nessun errore nei log, solo match che non
arrivavano. Ora la normalizzazione (sei cifre) sta in `app/geo.istat_a_sei`,
al punto d'ingresso, e `scripts/ripara_istat.py` sistema quello che era gia'
finito in archivio - gira a ogni avvio e dopo la prima volta non fa niente.

### Chi c'e' in macchina

L'app nasce per far viaggiare meno macchine. Il rischio speculare e' che,
mettendo in contatto sconosciuti, faccia nascere comitive in cui nessuno ha
mai fatto quel tipo di terreno: in scialpinismo un gruppo senza nessuno che
sappia cosa fare non e' una gita meno bella, e' una gita in cui un incidente
diventa grave, perche' non c'e' chi soccorre.

Non filtriamo nessuno. L'esperienza e' **auto-dichiarata** e non verifichiamo
niente: chi venisse escluso si organizzerebbe lo stesso nella chat del gruppo,
solo con meno informazioni di adesso. Quello che facciamo e' rendere visibile
di cosa e' fatto un gruppo **prima** che si formi. Nel profilo (`app/esperienza.py`
per le etichette, tutte in un posto solo):

| Campo | Perche' |
|---|---|
| da quanti inverni | il dato piu' onesto e piu' difficile da gonfiare |
| corsi | la domanda e' "hai fatto un corso", non "sei bravo" |
| difficolta' abituale | scala italiana, MS -> OSA |
| ARTVA, pala e sonda | ce l'hai o no |
| ultima prova di ricerca | mai / piu' di un anno fa / quest'inverno |

Le ultime due sono separate apposta: avere l'ARTVA e saperlo usare non sono la
stessa cosa, e chiederle insieme nasconde proprio il caso peggiore. E si chiede
**quando l'hai provato**, non "sai usarlo?", a cui rispondono di si' tutti.

Il riassunto in una riga compare accanto al nome ovunque si decida di
contattare qualcuno: nell'elenco Passaggi, nella scheda di un match e nel
messaggio Telegram di match. Chi non compila niente non sparisce: si legge
*esperienza non dichiarata*, che e' un'informazione anche quella.

E una cosa scritta dove si legge: **un passaggio in auto non e' una cordata.**
Chi guida non e' una guida, e ognuno decide la propria gita.

### Quanto ci metti ad arrivare

Ogni scheda gita dice quanti minuti di auto ci sono dal tuo comune, e da
quali paesi passi. Non e' un dato in piu': e' lo stesso percorso stradale che
serve al match. "Quanto ci metto?" e "chi passa da casa mia?" sono la stessa
domanda vista da due lati, e infatti condividono la cache (`Percorso`).

Il calcolo interseca il percorso con 867 poligoni comunali, quindi la prima
volta il server risponde `in_calcolo` e lo fa in sottofondo: l'app richiede
una volta dopo qualche secondo. Senza `ORS_API_KEY` il percorso e' una retta,
i minuti non vengono mostrati affatto (fra due valli il tempo in auto non ha
niente a che vedere con la distanza in linea d'aria) e i paesi sono dichiarati
come approssimazione.

### Il diario

Le gite fatte, con data e una nota. **Privato per scelta, non per
dimenticanza**: non esiste un endpoint per leggere il diario di un altro, non
entra nel riassunto dell'esperienza, non compare sulle uscite. Un contatore di
gite visibile diventa in fretta una classifica, e una classifica in montagna
spinge nella direzione sbagliata.

Raggruppato per stagione, non per anno civile: un inverno sta a cavallo di due
anni e "2026" spezzerebbe a meta' la stagione di chi scia a gennaio.

### Sapere

Rimandi, non copie. Tutto quello che serve per decidere una gita sta su siti
mantenuti da servizi valanghe e istituti di ricerca: ARPA Piemonte e
Meteo-France per i bollettini, EAWS per la scala del pericolo e i problemi
tipo, White Risk (SLF Davos) e AINEVA per imparare, il CAI per i corsi.

Se ti viene la tentazione di trascrivere qui una tabella vista in giro -
l'"Analyser" di SLF, per esempio - non farlo, e per due motivi. Non e' nostra:
e' un'opera protetta, con un autore e un traduttore. E soprattutto e' uno
strumento da campo per chi ha fatto un corso: metta' delle sue righe (durezza
degli strati, limite di strato, profondita' di penetrazione, test sul manto)
si compilano con la pala in mano, e nessun modello meteo le conosce.
Pre-compilarla coi nostri dati vorrebbe dire produrre una nostra valutazione
del pericolo, con l'aspetto di un giudizio professionale, in mano a chi non ha
mai fatto un corso.

### Prestazioni

Tre scelte che tengono l'app veloce e che non vanno disfatte:

- **I punteggi sono precalcolati** in tabella `condizioni` da `aggiorna.py`.
  La vista Weekend fa una query ordinata con limite: nessun ciclo sul
  catalogo, nessuna chiamata esterna dentro una richiesta.
- **Le richieste web non toccano mai la rete.** Meteo e bollettini si leggono
  dalla cache; a scaricarli pensa solo il cron.
- **Percorso, match e notifiche girano in sottofondo** dopo aver risposto al
  client.

```bash
python -m pytest -q     # 37 test, girano senza rete
```

---

## Licenza

Codice con licenza **MIT** (vedi [LICENSE](LICENSE)).

I dati degli itinerari, i bollettini e le previsioni **non** sono coperti da
quella licenza: appartengono alle rispettive fonti, con le licenze indicate
sopra, e vanno mantenute attribuzione e link.
