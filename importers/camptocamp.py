"""Import da Camptocamp.org (API pubblica, contenuti CC-BY-SA).

Prendiamo SOLO dati strutturati: nome, coordinate, quote, esposizione,
difficolta'. Nessun testo di relazione, nessuna foto. La descrizione resta
sul sito d'origine, a cui ogni scheda rimanda: e' il patto della licenza e
anche il modo giusto di stare in una community.

NOTA SUL FILTRO GEOGRAFICO
--------------------------
L'API accetta il parametro `bbox` ma di fatto lo ignora (provato: con la
bbox del Cuneese il totale SALE invece di scendere, e il primo risultato e'
nel Vercors). Quindi si scorre l'elenco completo e si filtra qui, sulle
coordinate che l'elenco stesso restituisce. Le pagine sono leggere; le
chiamate di dettaglio, che sono quelle pesanti, si fanno solo per gli
itinerari che cadono davvero nella zona.

Attenzione anche alla forma della geometria, che cambia fra i due endpoint:
  elenco   -> {"type": "Point", "coordinates": [x, y]}
  dettaglio-> {"geom": "{\\"type\\": \\"Point\\", ...}"}  (stringa JSON)
In entrambi i casi le coordinate sono in EPSG:3857 (metri), non in gradi.
"""
from __future__ import annotations

import asyncio
import json
import math
import time

import httpx

from app.config import settings
from app.db import session_scope
from app.geo import comune_di, dentro_bbox, mercator_to_wgs84, regione_eaws_di
from app.models import Gita

LICENZA = "CC-BY-SA (camptocamp.org)"
PER_PAGINA = 100


def wgs84_to_mercator(lon: float, lat: float) -> tuple[float, float]:
    x = lon * 20037508.34 / 180.0
    y = math.log(math.tan((90 + lat) * math.pi / 360.0)) / (math.pi / 180.0)
    return x, y * 20037508.34 / 180.0


def _coordinate(geometry) -> tuple[float, float] | None:
    """(lat, lon) da una geometria camptocamp, in qualunque delle sue forme."""
    if not geometry:
        return None

    candidati = []
    if isinstance(geometry, dict):
        if "coordinates" in geometry:          # elenco: GeoJSON diretto
            candidati.append(geometry)
        for chiave in ("geom", "geom_detail"):  # dettaglio: stringa JSON
            raw = geometry.get(chiave)
            if not raw:
                continue
            try:
                candidati.append(json.loads(raw) if isinstance(raw, str) else raw)
            except Exception:
                continue

    for g in candidati:
        coords = g.get("coordinates")
        if not coords:
            continue
        tipo = g.get("type")
        if tipo == "Point":
            x, y = coords[0], coords[1]
        elif tipo == "LineString":
            x, y = coords[0][0], coords[0][1]
        elif tipo == "MultiLineString":
            x, y = coords[0][0][0], coords[0][0][1]
        else:
            continue
        lon, lat = mercator_to_wgs84(x, y)
        return lat, lon
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
    """Il punto di partenza: nelle associazioni c'e' il waypoint di accesso,
    che e' esattamente il parcheggio che ci serve per meteo e routing."""
    ass = (dettaglio.get("associations") or {}).get("waypoints") or []
    preferiti = [w for w in ass if w.get("waypoint_type") in ("access", "access_ravine")]
    for w in preferiti + ass:
        p = _coordinate(w.get("geometry"))
        if p:
            return p
    return None


# ------------------------------------------------------------------ rete


async def _pagina(c: httpx.AsyncClient, area: int, offset: int) -> list[dict]:
    r = await c.get(
        f"{settings.url_camptocamp}/routes",
        params={"act": "skitouring", "a": area, "limit": PER_PAGINA, "offset": offset},
    )
    r.raise_for_status()
    return r.json().get("documents", [])


async def _dettaglio(c: httpx.AsyncClient, doc_id: int) -> dict | None:
    try:
        r = await c.get(f"{settings.url_camptocamp}/routes/{doc_id}")
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


# ----------------------------------------------------------------- import


async def importa(
    pagine_massime: int = 700, pausa_elenco: float = 0.15, pausa_dettaglio: float = 0.35
) -> int:
    headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
    candidati: list[tuple[dict, tuple[float, float]]] = []

    async with httpx.AsyncClient(timeout=45, headers=headers, follow_redirects=True) as c:
        # --- fase 1: scorri le aree e tieni solo quello che cade nella zona
        print("  fase 1: cerco gli itinerari nella zona...")
        visti: set[int] = set()   # un itinerario puo' stare in due aree
        esaminati = 0
        for area in settings.camptocamp_aree:
            offset = 0
            for pagina in range(pagine_massime):
                try:
                    documenti = await _pagina(c, area, offset)
                except Exception as e:
                    print(f"    area {area}, offset {offset}: {e}")
                    break
                if not documenti:
                    break
                for doc in documenti:
                    doc_id = doc.get("document_id")
                    if doc_id in visti:
                        continue
                    visti.add(doc_id)
                    esaminati += 1
                    attivita = doc.get("activities") or []
                    if attivita and "skitouring" not in attivita:
                        continue
                    punto = _coordinate(doc.get("geometry"))
                    if punto and dentro_bbox(punto[1], punto[0]):
                        candidati.append((doc, punto))
                offset += len(documenti)
                # NON fermarsi su una pagina corta: l'API a volte restituisce
                # 99 risultati invece di 100 pur avendone ancora. E oltre
                # offset 10000 risponde 400, quindi ci si ferma prima.
                if offset >= 9900:
                    print(f"    area {area}: raggiunto il tetto di paginazione")
                    break
                await asyncio.sleep(pausa_elenco)
            print(f"    area {area}: totale {esaminati} esaminati, "
                  f"{len(candidati)} nella zona")

        print(f"  fase 1 finita: {esaminati} esaminati, {len(candidati)} nella zona")
        if not candidati:
            print("  ATTENZIONE: nessun itinerario trovato nella bbox.")
            print(f"  Controlla BBOX nel .env (ora: {settings.bbox}).")
            return 0

        # --- fase 2: dettaglio solo per quelli buoni (qui sta il costo)
        print(f"  fase 2: scarico il dettaglio di {len(candidati)} itinerari...")
        nuovi = 0
        for i, (doc, punto) in enumerate(candidati, 1):
            if _gia_presente(str(doc["document_id"])):
                continue
            dett = await _dettaglio(c, doc["document_id"])
            await asyncio.sleep(pausa_dettaglio)
            if not dett:
                continue
            nome = _titolo(dett) or _titolo(doc)
            if not nome:
                continue
            attacco = _attacco(dett) or punto
            if _salva(doc, dett, nome, attacco, punto):
                nuovi += 1
            if i % 25 == 0:
                print(f"    {i}/{len(candidati)} - {nuovi} importate")

    return nuovi


def _gia_presente(fonte_id: str) -> bool:
    with session_scope() as db:
        return db.query(Gita).filter_by(fonte="camptocamp", fonte_id=fonte_id).first() is not None


def _salva(doc: dict, dett: dict, nome: str, attacco, cima) -> bool:
    with session_scope() as db:
        fonte_id = str(doc["document_id"])
        if db.query(Gita).filter_by(fonte="camptocamp", fonte_id=fonte_id).first():
            return False
        lat, lon = attacco
        c = comune_di(lat, lon) or {}
        autori = ", ".join(
            sorted({(a.get("name") or "") for a in (dett.get("associations", {}) or {}).get("users", [])})
        ) or None
        db.add(Gita(
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
            esposizione=",".join(dett.get("orientations") or doc.get("orientations") or []) or None,
            difficolta=dett.get("ski_rating") or dett.get("global_rating"),
            comune=c.get("nome"),
            istat=str(c["istat"]) if c.get("istat") else None,
            paese="IT" if c.get("istat") else "FR",
            eaws_region=regione_eaws_di(lat, lon),
            verificata=False,
        ))
    return True


if __name__ == "__main__":
    inizio = time.time()
    n = asyncio.run(importa())
    print(f"camptocamp: {n} gite importate in {time.time() - inizio:.0f}s")
