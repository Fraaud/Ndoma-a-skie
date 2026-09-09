"""Import da Skitour.fr (API ufficiale, topoguide CC-BY-SA 4.0).

Serve una chiave gratuita: la prendi dalla pagina di modifica del tuo profilo
su skitour.fr e la metti in SKITOUR_API_KEY. Limiti: 1000 chiamate/24h,
60/minuto - piu' che sufficienti, l'import si fa una volta.

Copre il versante francese delle stesse montagne che avete in casa
(Mercantour, Ubaye, alta Tinee): per le Marittime e' la fonte piu' ricca.

La licenza chiede di linkare la risorsa su skitour.fr e citare gli autori:
lo facciamo in ogni scheda, e' gia' previsto dal modello dati.
"""
from __future__ import annotations

import asyncio

import httpx

from app.config import settings
from app.db import session_scope
from app.geo import comune_di, dentro_bbox, regione_eaws_di
from app.models import Gita

LICENZA = "CC-BY-SA 4.0 (skitour.fr)"

# massicci di confine con la provincia di Cuneo
MASSICCI_INTERESSANTI = ("mercantour", "ubaye", "tinee", "tinée", "argentera",
                         "haute-tinee", "queyras", "parpaillon")


def _headers() -> dict:
    return {"cle": settings.skitour_api_key, "User-Agent": settings.user_agent,
            "Accept": "application/json"}


async def _get(c: httpx.AsyncClient, percorso: str, **params):
    r = await c.get(f"{settings.url_skitour}/{percorso}", params=params, headers=_headers())
    if r.status_code != 200:
        print(f"  skitour: {percorso} -> HTTP {r.status_code} {r.text[:120]}")
        return None
    try:
        return r.json()
    except Exception:
        return None


def _numero(v, default=None):
    try:
        return int(float(v))
    except Exception:
        return default


async def importa(pausa: float = 1.1) -> int:
    if not settings.skitour_api_key:
        print("  skitour: SKITOUR_API_KEY non impostata, salto")
        return 0

    nuovi = 0
    async with httpx.AsyncClient(timeout=40, follow_redirects=True) as c:
        massicci = await _get(c, "massifs") or []
        scelti = [
            m for m in massicci
            if any(k in str(m.get("nom", "")).lower() for k in MASSICCI_INTERESSANTI)
        ]
        print(f"  skitour: {len(scelti)} massicci di confine su {len(massicci)}")

        for m in scelti:
            mid = m.get("id") or m.get("id_massif")
            sommets = await _get(c, "sommets", massif=mid) or []
            await asyncio.sleep(pausa)
            for s in sommets:
                sid = s.get("id")
                topos = await _get(c, "topos", sommet=sid) or []
                await asyncio.sleep(pausa)
                for t in topos:
                    if _salva(t, s, m):
                        nuovi += 1
            print(f"  skitour: {m.get('nom')} -> totale {nuovi}")
    return nuovi


def _salva(topo: dict, sommet: dict, massif: dict) -> bool:
    depart = topo.get("depart") or {}
    lat = _numero_f(depart.get("lat") or topo.get("lat") or sommet.get("lat"))
    lon = _numero_f(depart.get("lon") or topo.get("lon") or sommet.get("lon"))
    if lat is None or lon is None or not dentro_bbox(lon, lat):
        return False

    fonte_id = str(topo.get("id"))
    with session_scope() as db:
        if db.query(Gita).filter_by(fonte="skitour", fonte_id=fonte_id).first():
            return False
        c = comune_di(lat, lon) or {}
        nome = topo.get("titre") or f"{sommet.get('nom')} - {topo.get('nom', '')}".strip(" -")
        db.add(Gita(
            nome=str(nome)[:200],
            fonte="skitour",
            fonte_id=fonte_id,
            fonte_url=f"https://skitour.fr/topos/{fonte_id}",
            licenza=LICENZA,
            autori=topo.get("auteur") or None,
            lat=lat, lon=lon,
            lat_cima=_numero_f(sommet.get("lat")),
            lon_cima=_numero_f(sommet.get("lon")),
            quota_min=_numero(depart.get("altitude")),
            quota_max=_numero(sommet.get("altitude")),
            dislivello=_numero(topo.get("denivele")),
            esposizione=topo.get("orientation") or None,
            difficolta=topo.get("cotation") or topo.get("difficulte") or None,
            comune=c.get("nome"),
            istat=str(c["istat"]) if c.get("istat") else None,
            paese="IT" if c.get("istat") else "FR",
            valle=massif.get("nom"),
            eaws_region=regione_eaws_di(lat, lon),
            verificata=False,
        ))
    return True


def _numero_f(v):
    try:
        return float(str(v).replace(",", "."))
    except Exception:
        return None


if __name__ == "__main__":
    print(f"skitour: {asyncio.run(importa())} gite importate")
