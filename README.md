# NDOMA A SKIÉ

Mini app Telegram per lo scialpinismo del Cuneese e del Mercantour.

1. **Scheda gita** — per ogni itinerario: meteo, qualita' della neve prevista
   (*powder score*) e pericolo valanghe ufficiale.
2. **Passaggi in auto** — chi offre posti, chi cerca un passaggio, chi cerca
   compagnia. Il match tiene conto dei **comuni che l'auto attraversa**, non
   della distanza in linea d'aria.

> ### Avvertenza
>
> **Questa applicazione non valuta la sicurezza di un itinerario e non
> sostituisce il bollettino valanghe ufficiale.**
>
> Il grado di pericolo mostrato e' quello emesso dagli enti competenti,
> semplicemente riportato: non viene calcolato ne' interpretato. Il punteggio
> sulla qualita' della neve dice **com'e' la neve da sciare**, non se sia
> prudente andarci: neve fresca abbondante con vento e' contemporaneamente la
> giornata piu' bella e la situazione in cui si staccano i lastroni.
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

## Deploy

Serve una macchina piccola (1 vCPU, 1 GB) con un dominio. Il database e'
SQLite: niente servizi esterni da gestire.

**1. Codice e ambiente**

```bash
git clone <repo> /opt/ndoma && cd /opt/ndoma
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
cp .env.example .env          # compila, con WEBAPP_URL = https://tuo.dominio
./venv/bin/python scripts/setup_geo.py
./venv/bin/python scripts/importa.py
```

**2. Due servizi systemd**, uno per il web e uno per il bot:

```ini
# /etc/systemd/system/ndoma-web.service
[Unit]
Description=Ndoma a skie - web
After=network.target

[Service]
WorkingDirectory=/opt/ndoma
ExecStart=/opt/ndoma/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
User=ndoma

[Install]
WantedBy=multi-user.target
```

Lo stesso file per il bot, con
`ExecStart=/opt/ndoma/venv/bin/python -m app.bot`.

```bash
systemctl enable --now ndoma-web ndoma-bot
```

**3. HTTPS.** Caddy fa da reverse proxy e prende il certificato da solo:

```
tuo.dominio {
    reverse_proxy 127.0.0.1:8000
}
```

**4. Aggiornamento notturno.** Va in cron, altrimenti la vista Weekend resta
ferma ai punteggi vecchi:

```
0 4 * * *  cd /opt/ndoma && ./venv/bin/python scripts/aggiorna.py >> data/cron.log 2>&1
```

**5. Backup.** Il database e' un file solo; con WAL attivo va copiato con il
comando di SQLite, non con `cp`:

```
30 4 * * *  sqlite3 /opt/ndoma/data/ndoma.db ".backup '/opt/backup/ndoma-$(date +\%u).db'"
```

**6. Aggiornare il codice**

```bash
git pull && ./venv/bin/pip install -r requirements.txt
systemctl restart ndoma-web ndoma-bot
```

Non serve altro: niente Redis, niente Postgres, niente code. Con qualche
decina di utenti questa configurazione sta larga.

---

## Com'e' fatto

```
app/
  main.py       API FastAPI + serve la mini app
  bot.py        bot Telegram: /start, promemoria del giovedi', notifiche
  models.py     Gita, Utente, Uscita, Match, Percorso, Comune, Condizioni, cache
  auth.py       verifica HMAC dell'initData Telegram (unico punto di sicurezza)
  geo.py        indici spaziali: comune di un punto, comuni attraversati
  schede.py     composizione scheda gita e calcolo dei punteggi
  services/     meteo, powder, valanghe, routing, match
  static/       mini app (html + css + un solo js)
importers/      camptocamp, skitour, osm
scripts/        check_fonti, setup_geo, importa, aggiorna, seed_demo
```

### Il powder score

Combina, sulle 72 ore prima della partenza: neve fresca a 24/48/72h alla quota
dell'attacco, vento durante e dopo la nevicata, temperatura durante la
nevicata come proxy della densita', ore dall'ultima nevicata, e un veto se e'
piovuto dopo la neve. Restituisce 0-5 con i fattori in chiaro.

Restituisce anche `avviso_valanghe`: neve fresca abbondante piu' vento e' la
giornata migliore e la ricetta del lastrone allo stesso tempo, e l'app lo dice
invece di mostrare cinque fiocchi e tacere. **Quell'avviso non va tolto
dall'interfaccia.**

### Il bollettino valanghe

Regole in `app/services/valanghe.py`, non negoziabili:

1. Nessun grado di pericolo calcolato da noi: solo quello ufficiale EAWS.
2. Nessun semaforo verde, nessun "si puo' andare".
3. Sempre visibili ente emittente, ora di emissione e link al bollettino integrale.
4. L'*evidenziatore* incrocia esposizione e quota della gita con quelle del
   problema segnalato: dice "questa gita ci passa dentro, leggi il bollettino",
   non se sia sicura.

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
