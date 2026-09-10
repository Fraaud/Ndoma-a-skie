"""Una giornata d'inverno vera, rigiocata sul prossimo weekend.

A che serve
-----------
Fuori stagione non c'e' neve e il bollettino piemontese e' sospeso: la vista
Weekend e le schede gita restano vuote e non si capisce come funzionera'
l'app d'inverno. Questo modulo prende un giorno d'inverno REALMENTE ACCADUTO
- meteo storico da Open-Meteo, bollettino valanghe dall'archivio EAWS - e lo
mette in cache spostando soltanto le etichette temporali. I valori restano
quelli veri: se il 14 febbraio erano caduti 40 cm, in app si leggono 40 cm.

La sicurezza qui non e' un dettaglio
------------------------------------
Un grado di pericolo mostrato senza contesto e' indistinguibile da quello di
oggi, e qualcuno potrebbe usarlo per decidere una gita. Per questo:

  1. l'ente emittente viene riscritto in "SIMULAZIONE - bollettino del
     <data>", e resta visibile in ogni scheda;
  2. finche' la simulazione e' attiva l'app mostra una fascia fissa in cima
     a ogni schermata, che nomina la data vera dei dati;
  3. non tocchiamo nulla dei contenuti del bollettino: cambia l'etichetta di
     chi lo ha emesso e quando, non una parola di cio' che dice.

Come si accende e come si spegne
--------------------------------
Una variabile d'ambiente, e non un comando da lanciare a mano:

    SIMULAZIONE_INVERNO=2026-02-14

Quando c'e', l'aggiornamento notturno ricarica la simulazione invece dei dati
di oggi - cioe' resta viva da sola, senza che nessuno se ne ricordi. Per
tornare alla realta' si toglie la variabile e si rilancia
scripts/aggiorna.py: i dati veri sovrascrivono quelli simulati.
"""
from __future__ import annotations

import asyncio
import datetime as dt

import httpx
from sqlalchemy.orm import Session

from app import schede
from app.config import settings
from app.models import CacheBollettino, CacheMeteo, Gita
from app.services import valanghe as val_srv

URL_ARCHIVIO = "https://archive-api.open-meteo.com/v1/archive"
ORARIE = ("temperature_2m,precipitation,rain,snowfall,snow_depth,"
          "wind_speed_10m,wind_gusts_10m,wind_direction_10m")

# Come si presenta un bollettino simulato. La stringa e' una sola, e i test
# controllano che ci sia: e' l'etichetta che impedisce di scambiarlo per
# quello di oggi.
ETICHETTA = "SIMULAZIONE - bollettino del {giorno}"


def attiva() -> bool:
    return giorno() is not None


def giorno() -> dt.date | None:
    """Il giorno d'inverno da rigiocare, se la simulazione e' accesa."""
    grezzo = (settings.simulazione_giorno or "").strip()
    if not grezzo:
        return None
    try:
        return dt.date.fromisoformat(grezzo)
    except ValueError:
        print(f"SIMULAZIONE_INVERNO='{grezzo}' non e' una data AAAA-MM-GG: ignorata")
        return None


def prossimo_sabato(oggi: dt.date | None = None) -> dt.date:
    oggi = oggi or dt.date.today()
    return oggi + dt.timedelta(days=(5 - oggi.weekday()) % 7)


def controlla_data(g: dt.date) -> list[str]:
    """Avvisi sulla data scelta. Lista vuota = nessun problema."""
    oggi = dt.date.today()
    if g >= oggi:
        return [f"{g} non e' un giorno passato: l'archivio meteo conserva solo "
                "cio' che e' gia' accaduto."]
    avvisi = []
    if (oggi - g).days < 6:
        avvisi.append(f"{g} e' molto recente: i dati di rianalisi arrivano con "
                      "qualche giorno di ritardo e potrebbero mancare.")
    if g.month in (5, 6, 7, 8, 9, 10):
        avvisi.append(f"{g} non e' un giorno d'inverno: di neve non ne troverai.")
    return avvisi


# ------------------------------------------------------------------- meteo


async def meteo_storico(c: httpx.AsyncClient, lat: float, lon: float,
                        g: dt.date, quota: int | None) -> dict | None:
    """Serie oraria reale attorno a `g`: quattro giorni prima, due dopo."""
    fine = min(g + dt.timedelta(days=2), dt.date.today() - dt.timedelta(days=1))
    params = {
        "latitude": round(lat, 4), "longitude": round(lon, 4),
        "start_date": (g - dt.timedelta(days=4)).isoformat(),
        "end_date": fine.isoformat(),
        "hourly": ORARIE, "timezone": "Europe/Rome",
    }
    if quota:
        params["elevation"] = int(quota)
    r = await c.get(URL_ARCHIVIO, params=params)
    if r.status_code != 200:
        print(f"    archivio meteo: HTTP {r.status_code} {r.text[:120]}")
        return None
    return r.json()


def sposta_nel_tempo(dati: dict, da: dt.date, a: dt.date) -> dict:
    """Riscrive gli orari come se quella giornata fosse `a`.

    I VALORI restano quelli veri: cambiano solo le etichette temporali, cosi'
    il conteggio della neve caduta (che guarda le 72 ore prima della partenza)
    trova la nevicata dove se l'aspetta.
    """
    scarto = a - da
    fuori = dict(dati)
    orarie = dict(dati.get("hourly", {}))
    if "time" in orarie:
        orarie["time"] = [
            (dt.datetime.fromisoformat(t) + scarto).strftime("%Y-%m-%dT%H:00")
            for t in orarie["time"]
        ]
    fuori["hourly"] = orarie
    giornaliere = dict(dati.get("daily", {}) or {})
    if "time" in giornaliere:
        giornaliere["time"] = [
            (dt.date.fromisoformat(x) + scarto).isoformat() for x in giornaliere["time"]
        ]
    fuori["daily"] = giornaliere or _giornaliere_da_orarie(orarie)
    return fuori


def _giornaliere_da_orarie(orarie: dict) -> dict:
    """L'archivio non restituisce il riepilogo giornaliero: lo ricaviamo."""
    per_giorno: dict[str, dict[str, list]] = {}
    for i, t in enumerate(orarie.get("time", [])):
        g = t[:10]
        d = per_giorno.setdefault(g, {"t": [], "neve": [], "prec": []})
        for chiave, dove in (("temperature_2m", "t"), ("snowfall", "neve"),
                             ("precipitation", "prec")):
            serie = orarie.get(chiave) or []
            if i < len(serie) and serie[i] is not None:
                d[dove].append(serie[i])
    giorni = sorted(per_giorno)
    return {
        "time": giorni,
        "temperature_2m_min": [min(per_giorno[g]["t"] or [None]) for g in giorni],
        "temperature_2m_max": [max(per_giorno[g]["t"] or [None]) for g in giorni],
        "snowfall_sum": [round(sum(per_giorno[g]["neve"]), 1) for g in giorni],
        "precipitation_sum": [round(sum(per_giorno[g]["prec"]), 1) for g in giorni],
    }


# --------------------------------------------------------------- bollettino


async def bollettino_storico(g: dt.date, tentativi: int = 10):
    """Cerca un bollettino EAWS reale a partire da `g`, andando indietro."""
    for scarto in range(tentativi):
        quando = g - dt.timedelta(days=scarto)
        try:
            trovati = await val_srv.scarica_bollettini(quando)
        except Exception as e:
            print(f"    {quando}: {e}")
            continue
        if trovati:
            print(f"    bollettini trovati per {quando}: {len(trovati)} micro-regioni")
            return trovati, quando
    return None


def _scrivi_bollettini(db: Session, per_regione: dict, giorno_vero: dt.date) -> int:
    oggi = dt.date.today()
    for regione, b in per_regione.items():
        b = dict(b)
        # l'unica cosa che cambiamo: chi lo ha emesso e quando. Del contenuto
        # non si tocca una parola.
        b["ente"] = ETICHETTA.format(giorno=giorno_vero)
        riga = (db.query(CacheBollettino)
                .filter_by(eaws_region=regione, giorno=oggi).one_or_none())
        if riga is None:
            riga = CacheBollettino(eaws_region=regione, giorno=oggi)
            db.add(riga)
        riga.payload = b
        riga.aggiornato_il = dt.datetime.now(dt.timezone.utc)
    db.commit()
    return len(per_regione)


# -------------------------------------------------------------- caricamento


async def carica(db: Session, g: dt.date | None = None, gite: list | None = None,
                 pausa: float = 0.2, verboso: bool = True) -> dict:
    """Riempie le cache con la giornata simulata. Stessa forma di aggiorna_tutto."""
    g = g or giorno()
    if g is None:
        raise ValueError("nessun giorno da simulare: manca SIMULAZIONE_INVERNO")
    bersaglio = prossimo_sabato()
    if gite is None:
        gite = db.query(Gita).filter(Gita.attiva.is_(True)).all()

    conteggi = {"gite": len(gite), "meteo": 0, "bollettini": 0, "punteggi": 0,
                "simulazione": g.isoformat()}
    if verboso:
        print(f"SIMULAZIONE: rigioco {g} sul {bersaglio} per {len(gite)} gite")
        for a in controlla_data(g):
            print(f"  attenzione: {a}")

    esito = await bollettino_storico(g)
    if esito:
        conteggi["bollettini"] = _scrivi_bollettini(db, *esito)
    elif verboso:
        print("    nessun bollettino trovato in quel periodo")

    oggi = dt.date.today()
    async with httpx.AsyncClient(timeout=40,
                                 headers={"User-Agent": settings.user_agent}) as c:
        for i, gita in enumerate(gite, 1):
            try:
                dati = await meteo_storico(c, gita.lat, gita.lon, g,
                                           gita.quota_min or gita.quota_max)
            except Exception as e:
                print(f"  meteo {gita.nome}: {e}")
                continue
            if not dati:
                continue
            riga = (db.query(CacheMeteo)
                    .filter_by(gita_id=gita.id, giorno=oggi).one_or_none())
            if riga is None:
                riga = CacheMeteo(gita_id=gita.id, giorno=oggi)
                db.add(riga)
            riga.payload = sposta_nel_tempo(dati, g, bersaglio)
            riga.aggiornato_il = dt.datetime.now(dt.timezone.utc)
            db.commit()
            conteggi["meteo"] += 1
            try:
                conteggi["punteggi"] += await schede.aggiorna_condizioni(db, gita)
            except Exception as e:
                print(f"  condizioni {gita.nome}: {e}")
            await asyncio.sleep(pausa)
            if verboso and i % 25 == 0:
                print(f"  {i}/{len(gite)}")

    if verboso:
        print(f"SIMULAZIONE caricata: {conteggi['meteo']} gite con meteo del {g}, "
              f"{conteggi['punteggi']} giornate scritte")
    return conteggi


def avviso_utente() -> dict | None:
    """Cio' che l'app deve mostrare in cima a ogni schermata, se accesa."""
    g = giorno()
    if g is None:
        return None
    return {
        "attiva": True,
        "giorno": g.isoformat(),
        "testo": (
            f"DATI DI PROVA. Neve e bollettino che vedi sono quelli veri del "
            f"{g.strftime('%d/%m/%Y')}, non di oggi: servono a far vedere come "
            f"funziona l'app fuori stagione. Non usarli per decidere una gita."
        ),
    }
