"""Import da Camptocamp.org (API pubblica, contenuti CC-BY-SA).

Prendiamo SOLO dati strutturati: nome, coordinate, quote, esposizione,
difficolta'. Nessun testo di relazione, nessuna foto. La descrizione resta
sul sito d'origine, a cui ogni scheda rimanda: e' il patto della licenza e
anche il modo giusto di stare in una community.
"""
from __future__ import annotations

import asyncio
import math
import time

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.db import session_scope
from app.geo import comune_di, dentro_bbox, mercator_to_wgs84, regione_eaws_di
from app.models import Gita

LICENZA = "CC-BY-SA (camptocamp.org)"


def wgs84_to_mercator(lon: float, lat: float) -> tuple[float, float]:
    x = lon * 20037508.34 / 180.0
    y = math.log(math.tan((90 + lat) * math.pi / 360.0)) / (math.pi / 180.0)
    return x, y * 20037508.34 / 180.0


def _punto_da_geom(geom: dict | None) -> tuple[float, float] | None:
    """geom.geom e' una stringa GeoJSON Point in EPSG:3857."""
    if not geom:
        return None
    import json

    for chiave in ("geom", "geom_detail"):
        raw = geom.get(chiave)
        if not raw:
            continue
        try:
            g = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            continue
        coords = g.get("coordinates")
        if not coords:
            continue
        if g.get("type") == "Point":
            x, y = coords[0], coords[1]
        elif g.get("type") in ("LineString", "MultiLineString"):
            piatto = coords[0] if g["type"] == "MultiLineString" else coords
            x, y = piatto[0][0], piatto[0][1]
        else:
            continue
        lon, lat = mercator_to_wgs84(x, y)
        return lat, lon
    return None


async def _elenco(client: httpx.AsyncClient, offset: int, limite: int = 100) -> dict:
    x1, y1 = wgs84_to_mercator(settings.bbox[0], settings.bbox[1])
    x2, y2 = wgs84_to_mercator(settings.bbox[2], settings.bbox[3])
    params = {
        "act": "skitouring",
        "limit": limite,
        "offset": offset,
        "bbox": f"{x1:.0f},{y1:.0f},{x2:.0f},{y2:.0f}",
    }
    r = await client.get(f"{settings.url_camptocamp}/routes", params=params)
    if r.status_code == 400:
        # il filtro bbox non e' accettato: si scarica tutto e si filtra in locale
        params.pop("bbox")
        r = await client.get(f"{settings.url_camptocamp}/routes", params=params)
    r.raise_for_status()
    return r.json()


async def _dettaglio(client: httpx.AsyncClient, doc_id: int) -> dict | None:
    try:
        r = await client.get(f"{settings.url_camptocamp}/routes/{doc_id}")
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def _titolo(doc: dict) -> str | None:
    for loc in doc.get("locales", []) or []:
        if loc.get("title"):
            titolo = loc["title"]
            if loc.get("title_prefix"):
                titolo = f"{loc['title_prefix']} - {titolo}"
            return titolo
    return None


def _attacco(dettaglio: dict) -> tuple[float, float] | None:
    """Il punto di partenza dell'itinerario: nelle associazioni c'e' il
    waypoint di accesso, che e' esattamente il parcheggio che ci serve."""
    ass = (dettaglio.get("associations") or {}).get("waypoints") or []
    preferiti = [w for w in ass if w.get("waypoint_type") in ("access", "access_ravine")]
    for w in preferiti + ass:
        p = _punto_da_geom(w.get("geometry"))
        if p:
            return p
    return None


async def importa(limite_totale: int = 2000, pausa: float = 0.35) -> int:
    """Scarica gli itinerari di scialpinismo nella bbox configurata."""
    nuovi = 0
    headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=40, headers=headers, follow_redirects=True) as c:
        offset, visti = 0, 0
        while visti < limite_totale:
            dati = await _elenco(c, offset)
            documenti = dati.get("documents", [])
            if not documenti:
                break
            for doc in documenti:
                visti += 1
                punto = _punto_da_geom(doc.get("geometry"))
                if not punto or not dentro_bbox(punto[1], punto[0]):
                    continue
                dett = await _dettaglio(c, doc["document_id"])
                await asyncio.sleep(pausa)  # gentilezza verso un server di volontari
                if not dett:
                    continue
                attacco = _attacco(dett) or punto
                nome = _titolo(dett) or _titolo(doc)
                if not nome:
                    continue
                if _salva(doc, dett, nome, attacco, punto):
                    nuovi += 1
            offset += len(documenti)
            print(f"  camptocamp: {visti} esaminati, {nuovi} importati")
            if len(documenti) < 100:
                break
    return nuovi


def _salva(doc: dict, dett: dict, nome: str, attacco, cima) -> bool:
    with session_scope() as db:  # type: Session
        fonte_id = str(doc["document_id"])
        if db.query(Gita).filter_by(fonte="camptocamp", fonte_id=fonte_id).first():
            return False
        lat, lon = attacco
        c = comune_di(lat, lon) or {}
        autori = ", ".join(
            sorted({(a.get("name") or "") for a in (dett.get("associations", {}) or {}).get("users", [])})
        ) or None
        g = Gita(
            nome=nome[:200],
            fonte="camptocamp",
            fonte_id=fonte_id,
            fonte_url=f"https://www.camptocamp.org/routes/{fonte_id}",
            licenza=LICENZA,
            autori=autori,
            lat=lat, lon=lon,
            lat_cima=cima[0] if cima else None,
            lon_cima=cima[1] if cima else None,
            quota_min=dett.get("elevation_min") or doc.get("elevation_min"),
            quota_max=dett.get("elevation_max") or doc.get("elevation_max"),
            dislivello=dett.get("height_diff_up") or doc.get("height_diff_up"),
            esposizione=",".join(dett.get("orientations") or []) or None,
            difficolta=dett.get("ski_rating") or dett.get("global_rating"),
            comune=c.get("nome"),
            istat=str(c["istat"]) if c.get("istat") else None,
            paese="FR" if not c.get("istat") else "IT",
            eaws_region=regione_eaws_di(lat, lon),
            verificata=False,
        )
        db.add(g)
    return True


if __name__ == "__main__":
    inizio = time.time()
    n = asyncio.run(importa())
    print(f"camptocamp: {n} gite importate in {time.time() - inizio:.0f}s")
