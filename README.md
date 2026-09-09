# NDOMA A SKIÉ

Mini app Telegram per lo scialpinismo del Cuneese e del Mercantour.
Progetto no-profit, senza pubblicita', costruito su fonti di dati aperte
con attribuzione.

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
> Attrezzatura, preparazione e giudizio sul terreno restano di chi va in
> montagna.

Due cose in una:

1. **Scheda gita** — per ogni itinerario: meteo, qualita' della neve prevista
   (*powder score*) e pericolo valanghe ufficiale. Utile dal primo giorno,
   anche con un solo utente.
2. **Passaggi in auto** — chi offre posti, chi cerca un passaggio, chi cerca
   compagnia. Il match tiene conto dei **comuni che l'auto attraversa**, non
   della distanza in linea d'aria: quello che conta e' essere sulla strada.

---

## Da dove vengono i dati

Solo fonti aperte, con attribuzione e link alla sorgente in ogni scheda.

| Cosa | Fonte | Licenza / accesso |
|---|---|---|
| Itinerari | [Camptocamp.org](https://www.camptocamp.org/api/) | CC-BY-SA, API pubblica |
| Itinerari (versante francese) | [Skitour.fr](https://skitour.fr/api/) | CC-BY-SA 4.0, chiave gratuita |
| Itinerari e parcheggi | OpenStreetMap (Overpass) | ODbL |
| Meteo | [Open-Meteo](https://open-meteo.com/) | gratuito non commerciale, senza chiave |
| Micro-regioni valanghe | [regions.avalanches.org](https://regions.avalanches.org/) | open data |
| Bollettini valanghe | [archivio EAWS](https://static.avalanche.report/eaws_bulletins/), [AINEVA](https://bollettini.aineva.it/) | bollettini ufficiali (Piemonte: ARPA Piemonte) |
| Confini comunali | ISTAT via [OnData/openpolis](https://www.confini-amministrativi.it/) | open data |
| Percorsi auto | [openrouteservice](https://openrouteservice.org/) | chiave gratuita (facoltativa) |

**Nessuno scraping.** Non copiamo relazioni, descrizioni, avvicinamenti o foto
da siti che non le rilasciano con licenza aperta — e nemmeno loro riassunti,
che restano opere derivate. Del catalogo ci servono otto campi: nome,
coordinate del parcheggio, quote, dislivello, esposizione, difficolta'. La
relazione si legge sulla fonte, che ogni scheda linka.

Se vuoi aggiungere una fonte chiusa (per esempio Gulliver, il riferimento del
Piemonte), la strada e' scrivere e chiedere. C'e' una bozza di mail pronta in
`docs/mail-gulliver.md`.

---

## Installazione (Mac, sviluppo locale)

### Strada breve

```bash
bash setup.sh     # ambiente, dipendenze, .env, test, diagnosi delle fonti
bash avvia.sh     # server web + bot
```

`setup.sh` si puo' rilanciare quante volte si vuole: salta i passaggi gia'
fatti. Il resto di questa sezione spiega gli stessi passaggi uno per uno.

### Strada lunga

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # poi apri .env e compila
```

### 1. Crea il bot

Su Telegram, scrivi a [@BotFather](https://t.me/BotFather):

```
/newbot        -> nome e username, ti da' il TOKEN
```

Metti il token in `.env` come `TELEGRAM_BOT_TOKEN`.

### 2. Controlla che le fonti rispondano

```bash
python scripts/check_fonti.py
```

Fallo **prima di tutto il resto**: ti dice in trenta secondi cosa risponde,
quali chiavi mancano e in che formato arrivano i dati. Se qualcosa e' rosso,
il posto da sistemare e' `app/config.py` (gli URL stanno tutti li').

> Fuori stagione i bollettini valanghe non esistono: in Piemonte l'emissione
> e' sospesa d'estate e riprende a inizio inverno. Se a settembre il punto 4
> e' giallo, e' normale.

### 3. Prepara i dati geografici

```bash
python scripts/setup_geo.py
```

Scarica confini comunali e micro-regioni valanghe, li ritaglia sulla bbox e
riempie la tabella dei comuni. Serve **prima** dell'import: senza, le gite
finiscono senza comune e senza zona valanghe.

### 4. Importa il catalogo

```bash
python scripts/importa.py                # tutte le fonti
python scripts/importa.py camptocamp     # una sola
```

L'import e' lento di proposito (una pausa fra le chiamate): stiamo chiedendo
dati a server tenuti in piedi da volontari.

### 5. Popola meteo e bollettini

```bash
python scripts/aggiorna.py
```

Da mettere in cron tutte le notti. **Non chiamare le API a ogni apertura
dell'app**: il venerdi' sera si collegano tutti insieme e con 200 gite si
sfora subito il tier gratuito.

```
0 4 * * *  cd /percorso/ndoma-a-skie && ./venv/bin/python scripts/aggiorna.py >> data/cron.log 2>&1
```

### 6. Avvia

Due processi, in due terminali:

```bash
uvicorn app.main:app --reload --port 8000     # web app + API
python -m app.bot                              # bot Telegram
```

Telegram pretende **https** per le mini app, quindi in locale serve un tunnel:

```bash
brew install cloudflared
cloudflared tunnel --url http://localhost:8000
```

Copia l'URL che ti stampa (`https://qualcosa.trycloudflare.com`) in `.env`
come `WEBAPP_URL`, riavvia il bot, e su Telegram fai `/start`.

Verifica veloce dello stato: <http://localhost:8000/api/salute>

---

## Com'e' fatto

```
app/
  main.py            API FastAPI + serve la mini app
  bot.py             bot Telegram: /start, promemoria del giovedi', notifiche
  models.py          Gita, Utente, Uscita, Match, Percorso, Comune, cache
  auth.py            verifica HMAC dell'initData Telegram (unico punto di sicurezza)
  geo.py             indici spaziali: comune di un punto, comuni attraversati
  schede.py          composizione scheda gita + cache meteo/bollettini
  services/
    meteo.py         Open-Meteo
    powder.py        formula della qualita' della neve
    valanghe.py      bollettini EAWS + evidenziatore esposizione/quota
    routing.py       percorso auto e comuni attraversati
    match.py         punteggio di compatibilita' fra uscite
  static/            mini app (html + css + un solo js)
importers/           camptocamp, skitour, osm
scripts/             check_fonti, setup_geo, importa, aggiorna
```

### Il powder score

Combina, sulle 72 ore prima della partenza:

- neve fresca a 24/48/72h alla quota dell'attacco
- vento durante e dopo la nevicata (e' il vento che trasforma la polvere in
  crosta e lastroni)
- temperatura durante la nevicata, come proxy della densita'
- ore dall'ultima nevicata
- veto se e' piovuto dopo la neve

Restituisce 0-5 con l'elenco dei fattori in chiaro: chi legge deve poter
capire *perche'*, non fidarsi di un numero.

**E restituisce anche `avviso_valanghe`.** Neve fresca abbondante piu' vento
e' insieme la giornata piu' bella e la ricetta del lastrone: l'app lo dice
esplicitamente invece di mostrare cinque fiocchi e tacere. Non togliere
quell'avviso dall'interfaccia.

### Il bollettino valanghe

Regole di prodotto, in `app/services/valanghe.py`:

1. Nessun grado di pericolo calcolato da noi: solo quello ufficiale EAWS.
2. Nessun semaforo verde, nessun "si puo' andare".
3. Sempre visibili ente emittente, ora di emissione e link al bollettino integrale.
4. L'*evidenziatore* incrocia esposizione e quota della gita con quelle del
   problema segnalato. Dice "questa gita ci passa dentro, leggi il bollettino".
   Non dice se la gita e' sicura, e non deve mai farlo.

### Il match

Punteggio (soglia 5):

| Criterio | Punti |
|---|---|
| il comune di chi cerca e' **sul percorso** di chi guida | +4 |
| entro 8 km dal percorso | +2,5 |
| stessa gita | +3 |
| stessa data | +3 (entro flessibilita': +2) |
| stessa zona / valle | +1,5 |
| orari compatibili | +0,5 |

I percorsi si calcolano una volta per coppia (comune, gita) e restano in
cache: le combinazioni reali sono poche centinaia.

Una regola importante, presidiata da un test: **il match non usa mai la
distanza in linea d'aria fra due attacchi.** In montagna dodici chilometri in
linea d'aria possono essere due valli diverse e novanta chilometri di strada,
perche' bisogna scendere a fondovalle e risalire. L'unica vicinanza che conta
e' quella stradale.

---

## Contribuire

Le pull request sono benvenute, soprattutto da chi va in montagna nelle stesse
valli. Prima di aprirne una:

```bash
source venv/bin/activate
python -m pytest -q          # i test girano senza rete, devono passare tutti
```

Tre cose che non vengono accettate, per come e' pensato il progetto:

1. **Codice che scarica dati da fonti chiuse.** Niente scraping di siti che non
   rilasciano i contenuti con licenza aperta, nemmeno "solo i dati" o "solo un
   riassunto": in UE l'estrazione di una parte sostanziale di una banca dati e'
   protetta di per se', e un riassunto e' comunque un'opera derivata. Se una
   fonte serve, si scrive e si chiede.
2. **Qualunque cosa somigli a un giudizio di sicurezza.** Nessun semaforo verde,
   nessun grado di pericolo calcolato dall'app, nessun "oggi si puo' andare".
   Il bollettino si riporta.
3. **Rimozione dell'avviso valanghe** dalle giornate con molta neve fresca e
   vento, per quanto rovini l'estetica di un punteggio a cinque fiocchi.

Per il resto: codice in italiano per il dominio (gita, uscita, attacco) e in
inglese per la tecnica, come nel resto del progetto.

## Farlo girare per un'altra valle

Il progetto non ha niente di specifico del Cuneese se non una riga di
configurazione. Per adattarlo a un'altra zona:

1. cambia `BBOX` nel `.env` con il riquadro della tua zona
2. in `importers/skitour.py`, aggiorna `MASSICCI_INTERESSANTI` con i massicci
   di confine che ti interessano (o togli quella fonte se sei lontano dalla
   Francia)
3. in `app/config.py`, `eaws_countries` elenca i paesi di cui scaricare le
   micro-regioni valanghe

Poi `setup_geo.py` e `importa.py` fanno il resto. Se lo attivi per un'altra
valle, facci sapere: fa piacere.

---

## Da fare dopo

- [ ] scrivere a Gulliver (bozza in `docs/mail-gulliver.md`)
- [ ] seed manuale: 15 gite preferite a testa dal gruppo. Chi riempie il
      catalogo diventa il primo utente, ed e' cosi' che si parte davvero
- [ ] deploy su un server piccolo quando funziona in locale
- [ ] rimborso benzina calcolato sui km del percorso (i dati ci sono gia')
- [ ] gite ricorrenti ("tutti i sabati parto da Cuneo alle 6")

Volutamente **non** nella v1: pagamenti, rating degli utenti, chat interna.
Il rimborso benzina lo decidono in chat come hanno sempre fatto.

---

## Licenza e responsabilita'

Il codice e' rilasciato con licenza **MIT** (vedi [LICENSE](LICENSE)): usalo,
modificalo, fanne una versione per la tua valle.

I dati degli itinerari, i bollettini e le previsioni **non** sono coperti da
quella licenza: appartengono alle rispettive fonti, con le licenze indicate
sopra, e vanno mantenute attribuzione e link.

Questa app **non valuta la sicurezza di un itinerario** e non sostituisce il
bollettino valanghe ufficiale, la preparazione, l'attrezzatura e il giudizio
di chi va in montagna.
