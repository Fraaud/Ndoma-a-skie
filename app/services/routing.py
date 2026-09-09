"""Percorso auto partenza -> attacco e comuni attraversati.

E' il pezzo che rende il match utile: non conta la distanza in linea d'aria
tra due persone, conta se il passeggero sta SULLA STRADA di chi guida.
In provincia di Cuneo la geografia aiuta (valli radiali: tutti passano
dall'imbocco valle), ma la regola vale ovunque.

Le coppie (comune di partenza, gita) sono poche centinaia: si calcolano una
volta e si tengono in cache per sempre.
"""
from __future__ import annotations

import datetime as dt

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.geo import indice_comuni
from app.models import Gita, Percorso


async def _ors(lat1: float, lon1: float, lat2: float, lon2: float) -> dict | None:
    if not settings.ors_api_key:
        return None
    body = {"coordinates": [[lon1, lat1], [lon2, lat2]], "instructions": False}
    headers = {
        "Authorization": settings.ors_api_key,
        "Content-Type": "application/json",
        "User-Agent": settings.user_agent,
    }
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(settings.url_ors_directions, json=body, headers=headers)
        if r.status_code != 200:
            return None
        return r.json()


def _linea_retta(lat1, lon1, lat2, lon2, passi: int = 40) -> list[list[float]]:
    return [
        [lon1 + (lon2 - lon1) * i / passi, lat1 + (lat2 - lat1) * i / passi]
        for i in range(passi + 1)
    ]


async def calcola_percorso(
    db: Session, istat_partenza: str, lat_p: float, lon_p: float, gita: Gita
) -> Percorso:
    esistente = (
        db.query(Percorso)
        .filter_by(istat_partenza=istat_partenza, gita_id=gita.id)
        .one_or_none()
    )
    if esistente:
        return esistente

    dati = await _ors(lat_p, lon_p, gita.lat, gita.lon)
    if dati and dati.get("features"):
        feat = dati["features"][0]
        coords = feat["geometry"]["coordinates"]
        somm = feat.get("properties", {}).get("summary", {})
        km = (somm.get("distance") or 0) / 1000.0
        minuti = (somm.get("duration") or 0) / 60.0
        geom = feat["geometry"]
    else:
        # senza chiave ORS ripieghiamo sulla retta: il corridoio e' approssimato
        # ma nelle valli alpine, dove esiste una sola strada, funziona sorprendentemente bene.
        coords = _linea_retta(lat_p, lon_p, gita.lat, gita.lon)
        km = minuti = None
        geom = {"type": "LineString", "coordinates": coords}

    comuni = indice_comuni().attraversati((c[0], c[1]) for c in coords)
    istat_list = [str(c["istat"]) for c in comuni if c.get("istat")]

    p = Percorso(
        istat_partenza=istat_partenza,
        gita_id=gita.id,
        km=km,
        minuti=minuti,
        comuni_istat=istat_list,
        geometria=geom,
        calcolato_il=dt.datetime.now(dt.timezone.utc),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p
