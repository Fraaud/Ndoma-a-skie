"""Le condizioni raccontate da chi c'e' stato: vocabolario chiuso.

Perche' esiste questo file
--------------------------
Il bollettino dice com'e' il manto su una micro-regione intera; il modello
meteo dice quanti centimetri sono caduti. Nessuno dei due sa se la strada
era aperta fino all'attacco, se la traccia c'era, se sotto i 1800 m si
scendeva sull'erba. Quello lo sa solo chi e' passato ieri.

Perche' le etichette sono chiuse
--------------------------------
Un campo di testo libero, in questo posto, diventa in fretta un consiglio:
"tranquilla, si va", "condizioni ottime", "nessun problema". E' esattamente
la frase che fa partire qualcuno senza leggere il bollettino, e non e' una
frase che vogliamo far scrivere dalla nostra app. Con le etichette si
racconta un FATTO OSSERVATO - la neve era crosta, la strada era chiusa a
Sant'Anna - e il giudizio resta dove deve stare: nel bollettino e poi in chi
guarda il pendio.

Per la stessa ragione fra le etichette non ce n'e' nessuna che dica "era
sicuro", "si poteva andare", "nessun pericolo". Non e' una dimenticanza:
c'e' un test che lo verifica, `test_nessuna_etichetta_da_giudizi`. Se un
giorno viene la tentazione di aggiungerne una, quel test si mette a
protestare, ed e' il suo lavoro.

La nota libera resta - un dettaglio che le etichette non prendono serve -
ma e' corta (140 caratteri) e nell'interfaccia lo diciamo: serve a
raccontare cosa hai visto, non a dare consigli.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

# Com'era la neve. Sono i nomi che si usano parlando al parcheggio: chi
# scia li riconosce senza spiegazioni, e sono descrizioni di cosa avevi
# sotto gli sci, non voti.
NEVE = {
    "polvere": "polvere",
    "trasformata": "neve trasformata",
    "crosta_portante": "crosta portante",
    "crosta_rottura": "crosta da rottura",
    "umida": "neve umida",
    "ventata": "neve ventata",
    "ghiaccio": "ghiaccio",
    "fondo_duro": "fondo duro",
}

# Piu' di tre etichette non descrivono piu' niente: se la neve era polvere,
# crosta, umida, ventata e ghiaccio insieme, quello che si e' scritto e'
# "c'era la neve".
MAX_NEVE = 3

# La traccia: una sola risposta, sono alternative.
TRACCIA = {
    "battuta": "traccia battuta",
    "parziale": "traccia solo in parte",
    "da_tracciare": "tutto da tracciare",
}

# L'accesso in auto. E' il pezzo che l'app ha piu' bisogno di sapere: da
# qui e' nata, da sei macchine ferme in un piazzale.
ACCESSO = {
    "strada_aperta": "strada aperta fino all'attacco",
    "strada_chiusa": "strada chiusa prima",
    "catene": "servono catene o gomme da neve",
    "parcheggio_pieno": "parcheggio pieno",
    "parcheggio_non_pulito": "parcheggio non spalato",
}

# Quote plausibili sulle Marittime e nel Mercantour: il piu' basso attacco
# sta sotto i 900 m, la cima piu' alta e' l'Argentera a 3297.
QUOTA_MIN, QUOTA_MAX = 500, 3400

MAX_NOTA = 140

# Una segnalazione vecchia di un mese non racconta questo inverno: si
# smette di mostrarla invece di lasciarla invecchiare in fondo alla scheda.
GIORNI_VALIDI = 30

# Oltre questi giorni la segnalazione si mostra, ma marcata: la neve cambia
# in una notte di vento.
GIORNI_FRESCA = 4

# Parole che in questo posto non devono comparire in nessuna etichetta:
# dicono se si poteva andare, non cosa si e' visto. Il test le controlla.
PAROLE_DI_GIUDIZIO = (
    "sicur", "insicur", "tranquill", "pericol", "rischi", "consigl",
    "sconsigl", "ottim", "perfett", "brutt", "andare", "evitare",
    "adatt", "facile", "difficile",
)


def _lista(valori, ammessi: dict, massimo: int) -> list[str]:
    """Tiene solo le etichette che esistono, senza doppioni, in ordine."""
    fuori = []
    for v in valori or []:
        chiave = str(v).strip()
        if chiave in ammessi and chiave not in fuori:
            fuori.append(chiave)
    return fuori[:massimo]


def _uno(valore, ammessi: dict) -> Optional[str]:
    v = str(valore or "").strip()
    return v if v in ammessi else None


def pulisci(dati: dict) -> dict:
    """Normalizza quello che arriva dal modulo: fuori i valori inventati.

    Stessa logica di app/esperienza.py: un valore che non e' nel
    vocabolario non e' un errore da mostrare all'utente, e' un valore che
    non esiste e viene semplicemente lasciato fuori.
    """
    quota = dati.get("quota_cambio")
    try:
        quota = int(quota)
    except (TypeError, ValueError):
        quota = None
    if quota is not None and not (QUOTA_MIN <= quota <= QUOTA_MAX):
        quota = None

    nota = (dati.get("nota") or "").strip()

    return {
        "neve": _lista(dati.get("neve"), NEVE, MAX_NEVE),
        "traccia": _uno(dati.get("traccia"), TRACCIA),
        "accesso": _lista(dati.get("accesso"), ACCESSO, len(ACCESSO)),
        "quota_cambio": quota,
        "nota": nota[:MAX_NOTA] or None,
    }


def vuota(pulita: dict) -> bool:
    """Una segnalazione senza nessuna etichetta non dice niente: non si salva."""
    return not (pulita.get("neve") or pulita.get("traccia")
                or pulita.get("accesso") or pulita.get("nota"))


def etichette(s) -> list[str]:
    """Le etichette in parole, nell'ordine in cui si leggono bene.

    La quota resta un'etichetta a se'. Attaccarla a una delle etichette
    della neve - "crosta portante fino a 2100 m" - direbbe una cosa che
    l'utente non ha dichiarato: l'ordine in cui ha toccato le pillole e'
    l'ordine in cui gli sono venute in mente, non quello delle quote.
    """
    fuori = [NEVE[k] for k in (s.neve or []) if k in NEVE]
    if s.quota_cambio:
        fuori.append(f"cambiava verso i {s.quota_cambio} m")
    if s.traccia in TRACCIA:
        fuori.append(TRACCIA[s.traccia])
    fuori += [ACCESSO[k] for k in (s.accesso or []) if k in ACCESSO]
    return fuori


def giorni_fa(giorno: dt.date, oggi: dt.date | None = None) -> int:
    return max(0, ((oggi or dt.date.today()) - giorno).days)


def quando(g: int) -> str:
    """Quanto e' vecchia, in parole.

    L'eta' di una segnalazione conta piu' del suo contenuto: "polvere" di
    tre settimane fa e' un dato sul passato, non sul weekend.
    """
    if g <= 0:
        return "oggi"
    if g == 1:
        return "ieri"
    if g < 7:
        return f"{g} giorni fa"
    if g < 14:
        return "la settimana scorsa"
    return f"{g} giorni fa"


VOCABOLARIO = {
    "neve": NEVE,
    "traccia": TRACCIA,
    "accesso": ACCESSO,
    "max_neve": MAX_NEVE,
    "max_nota": MAX_NOTA,
    "quota_min": QUOTA_MIN,
    "quota_max": QUOTA_MAX,
    "giorni_validi": GIORNI_VALIDI,
    "giorni_fresca": GIORNI_FRESCA,
    # lo mandiamo al client perche' la frase compaia sotto il modulo, dove
    # uno sta scrivendo, e non solo in questo commento
    "avvertenza": (
        "Qui si racconta cosa hai visto, non se si puo' andare. Fra le "
        "etichette non ce n'e' nessuna che dica «era sicuro», e non "
        "e' una dimenticanza: quel giudizio lo fa il bollettino, e poi lo "
        "fai tu sul posto."
    ),
}
