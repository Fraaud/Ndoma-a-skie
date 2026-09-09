"""Carica una giornata d'inverno VERA per provare l'app fuori stagione.

A settembre non c'e' neve e il bollettino piemontese e' sospeso, quindi la
scheda gita e la vista Weekend non mostrano nulla di significativo. Questo
script prende un giorno d'inverno realmente accaduto - meteo storico da
Open-Meteo e bollettino valanghe dall'archivio EAWS - e lo mette in cache
spostando gli orari sul prossimo weekend, cosi' tutta la catena
(punteggio neve, evidenziatore, ordinamento) gira su dati reali.

    python scripts/prova_inverno.py                      # Limone, 14/02/2026
    python scripts/prova_inverno.py --data 2026-01-20
    python scripts/prova_inverno.py --tutte              # tutto il catalogo
    python scripts/prova_inverno.py --pulisci            # rimuove la simulazione

ATTENZIONE
----------
I dati caricati sono REALI ma di un ALTRO GIORNO. Per non lasciare che
qualcuno li scambi per il bollettino di oggi, l'ente emittente viene
riscritto come "SIMULAZIONE - bollettino del <data>" e resta visibile in
ogni scheda. Prima di far usare l'app a qualcuno, lancia --pulisci.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import schede  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.geo import distanza_km  # noqa: E402
from app.models import CacheBollettino, CacheMeteo, Condizioni, Gita  # noqa: E402
from app.services import valanghe as val_srv  # noqa: E402

LIMONE = (44.2027, 7.5772)
URL_ARCHIVIO = "https://archive-api.open-meteo.com/v1/archive"
ORARIE = ("temperature_2m,precipitation,rain,snowfall,snow_depth,"
          "wind_speed_10m,wind_gusts_10m,wind_direction_10m")


def prossimo_sabato() -> dt.date:
    oggi = dt.date.today()
    return oggi + dt.timedelta(days=(5 - oggi.weekday()) % 7)


# ------------------------------------------------------------------ meteo


async def meteo_storico(c: httpx.AsyncClient, lat: float, lon: float,
                        giorno: dt.date, quota: int | None) -> dict | None:
    """Serie oraria reale attorno a `giorno` (4 giorni prima, 2 dopo)."""
    params = {
        "latitude": round(lat, 4), "longitude": round(lon, 4),
        "start_date": (giorno - dt.timedelta(days=4)).isoformat(),
        "end_date": (giorno + dt.timedelta(days=2)).isoformat(),
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
    il calcolo del punteggio (che guarda le 72 ore prima della partenza)
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
            (dt.date.fromisoformat(g) + scarto).isoformat() for g in giornaliere["time"]
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


# -------------------------------------------------------------- bollettino


async def bollettino_storico(giorno: dt.date, tentativi: int = 10) -> tuple[dict, dt.date] | None:
    """Cerca un bollettino EAWS reale a partire da `giorno`, andando indietro."""
    for scarto in range(tentativi):
        g = giorno - dt.timedelta(days=scarto)
        try:
            trovati = await val_srv.scarica_bollettini(g)
        except Exception as e:
            print(f"    {g}: {e}")
            continue
        if trovati:
            print(f"    bollettini trovati per {g}: {len(trovati)} micro-regioni")
            return trovati, g
    return None


# ------------------------------------------------------------------ main


async def principale(giorno: dt.date, tutte: bool, raggio: float) -> None:
    init_db()
    db = SessionLocal()
    sabato = prossimo_sabato()

    gite = db.query(Gita).filter(Gita.attiva.is_(True)).all()
    if not tutte:
        gite = [g for g in gite if distanza_km(g.lat, g.lon, *LIMONE) <= raggio]
    if not gite:
        print("Nessuna gita selezionata. Prova --tutte o alza --raggio.")
        return
    print(f"Simulo {giorno} sul {sabato} per {len(gite)} gite\n")

    print("1) Bollettino valanghe dall'archivio EAWS")
    esito = await bollettino_storico(giorno)
    per_regione: dict[str, dict] = {}
    if esito:
        per_regione, giorno_boll = esito
        for regione, b in per_regione.items():
            b = dict(b)
            b["ente"] = f"SIMULAZIONE - bollettino del {giorno_boll}"
            riga = (db.query(CacheBollettino)
                    .filter_by(eaws_region=regione, giorno=dt.date.today()).one_or_none())
            if riga is None:
                riga = CacheBollettino(eaws_region=regione, giorno=dt.date.today())
                db.add(riga)
            riga.payload = b
            riga.aggiornato_il = dt.datetime.now(dt.timezone.utc)
        db.commit()
    else:
        print("    nessun bollettino trovato in quel periodo")

    print("\n2) Meteo storico e punteggi")
    headers = {"User-Agent": settings.user_agent}
    fatte = 0
    async with httpx.AsyncClient(timeout=40, headers=headers) as c:
        for i, g in enumerate(gite, 1):
            dati = await meteo_storico(c, g.lat, g.lon, giorno, g.quota_min or g.quota_max)
            if not dati:
                continue
            spostati = sposta_nel_tempo(dati, giorno, sabato)
            riga = (db.query(CacheMeteo)
                    .filter_by(gita_id=g.id, giorno=dt.date.today()).one_or_none())
            if riga is None:
                riga = CacheMeteo(gita_id=g.id, giorno=dt.date.today())
                db.add(riga)
            riga.payload = spostati
            riga.aggiornato_il = dt.datetime.now(dt.timezone.utc)
            db.commit()
            await schede.aggiorna_condizioni(db, g)
            fatte += 1
            await asyncio.sleep(0.2)
            if i % 10 == 0:
                print(f"    {i}/{len(gite)}")

    print(f"\n3) Risultato: {fatte} gite con dati reali del {giorno}\n")
    migliori = (
        db.query(Condizioni, Gita).join(Gita, Gita.id == Condizioni.gita_id)
        .filter(Condizioni.giorno == sabato)
        .order_by(Condizioni.punteggio.desc()).limit(10).all()
    )
    for c_, g in migliori:
        print(f"  {c_.punteggio:>4}  {g.nome[:42]:<44} grado {c_.grado_valanghe or '-'}"
              f"  {(c_.fattore or '')[:38]}")
        if c_.avviso:
            print(f"        ! {c_.avviso[:80]}")
    if not migliori:
        print("  nessun punteggio: guarda gli errori sopra")

    print("\nApri l'app: la vista Weekend mostra questi dati.")
    print("Ricorda: sono REALI ma di un altro giorno. Quando hai finito:")
    print("  python scripts/prova_inverno.py --pulisci")
    db.close()


def pulisci() -> None:
    init_db()
    db = SessionLocal()
    b = db.query(CacheBollettino).delete()
    m = db.query(CacheMeteo).delete()
    c = db.query(Condizioni).delete()
    db.commit()
    db.close()
    print(f"Rimossi {b} bollettini, {m} meteo, {c} punteggi.")
    print("Rilancia scripts/aggiorna.py per tornare ai dati di oggi.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Prova l'app con una giornata d'inverno vera")
    p.add_argument("--data", default="2026-02-14", help="giorno d'inverno da simulare")
    p.add_argument("--tutte", action="store_true", help="tutto il catalogo, non solo Limone")
    p.add_argument("--raggio", type=float, default=15.0, help="km attorno a Limone")
    p.add_argument("--pulisci", action="store_true", help="rimuove la simulazione")
    a = p.parse_args()

    if a.pulisci:
        pulisci()
    else:
        asyncio.run(principale(dt.date.fromisoformat(a.data), a.tutte, a.raggio))
