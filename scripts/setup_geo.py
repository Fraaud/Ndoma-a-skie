"""Scarica e prepara i due strati geografici di base.

  1. confini comunali italiani (ISTAT, ridistribuiti da OnData/openpolis)
     -> servono per capire QUALI PAESI ATTRAVERSA chi guida
  2. micro-regioni EAWS (regions.avalanches.org)
     -> servono per associare a ogni gita il suo bollettino valanghe

I file vengono ritagliati sulla bbox configurata: da 60 MB si scende a pochi MB
e il caricamento in memoria diventa istantaneo.

Uso:  python scripts/setup_geo.py
"""
from __future__ import annotations

import json
import os
import sys

import httpx
from shapely.geometry import box, shape

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings  # noqa: E402
from app.db import init_db, session_scope  # noqa: E402
from app.models import Comune  # noqa: E402

MARGINE = 0.6  # gradi di margine attorno alla bbox: i percorsi partono da fuori


def _scarica(url: str) -> dict | None:
    print(f"  scarico {url}")
    try:
        with httpx.Client(timeout=180, follow_redirects=True,
                          headers={"User-Agent": settings.user_agent}) as c:
            r = c.get(url)
            if r.status_code != 200:
                print(f"  -> HTTP {r.status_code}")
                return None
            return r.json()
    except Exception as e:
        print(f"  -> errore: {e}")
        return None


def _ritaglia(gj: dict, riquadro) -> dict:
    tenute = []
    for f in gj.get("features", []):
        try:
            g = shape(f["geometry"])
        except Exception:
            continue
        if g.is_empty or not g.intersects(riquadro):
            continue
        tenute.append(f)
    return {"type": "FeatureCollection", "features": tenute}


def comuni() -> int:
    gj = _scarica(settings.url_comuni_it)
    if not gj:
        print("  ATTENZIONE: confini comunali non scaricati. Il match sui comuni")
        print("  attraversati non funzionera' finche' non risolvi questo.")
        return 0
    b = settings.bbox
    riquadro = box(b[0] - MARGINE, b[1] - MARGINE, b[2] + MARGINE, b[3] + MARGINE)
    ritagliato = _ritaglia(gj, riquadro)
    with open(settings.comuni_geojson, "w", encoding="utf-8") as f:
        json.dump(ritagliato, f)
    print(f"  comuni tenuti: {len(ritagliato['features'])}")
    n = popola_comuni(ritagliato)
    print(f"  comuni in database: {n}")
    return n


def popola_comuni(gj: dict | None = None) -> int:
    """Scrive in archivio l'elenco dei comuni, leggendolo dal file ritagliato.

    Sta separata dallo scaricamento perche' i due strati geografici viaggiano
    gia' pronti nel repository: chi installa da li' (Railway) ha il file ma
    non le righe in archivio, e senza quelle non funziona la ricerca del
    comune di partenza - cioe' il campo che apre tutta la pubblicazione di
    un'uscita. Era un buco silenzioso: l'app partiva benissimo e l'elenco
    dei paesi restava vuoto.
    """
    if gj is None:
        if not os.path.exists(settings.comuni_geojson):
            return 0
        with open(settings.comuni_geojson, encoding="utf-8") as f:
            gj = json.load(f)

    init_db()
    n = 0
    with session_scope() as db:
        for feat in gj.get("features", []):
            p = feat.get("properties", {})
            istat = str(p.get("com_istat_code") or p.get("com_istat_code_num")
                        or p.get("pro_com_t") or p.get("PRO_COM_T") or "").strip()
            nome = p.get("name") or p.get("COMUNE") or p.get("comune")
            if not istat or not nome:
                continue
            try:
                centro = shape(feat["geometry"]).representative_point()
            except Exception:
                continue
            if db.get(Comune, istat):
                continue
            db.add(Comune(
                istat=istat, nome=nome,
                provincia=p.get("prov_name") or p.get("DEN_UTS"),
                regione=p.get("reg_name") or p.get("DEN_REG"),
                lat=centro.y, lon=centro.x,
            ))
            n += 1
    return n


def micro_regioni_eaws() -> int:
    feature = []
    for regione in settings.eaws_regioni:
        gj = None
        for tmpl in (settings.url_eaws_regions_latest_tmpl, settings.url_eaws_regions_tmpl):
            gj = _scarica(tmpl.format(regione=regione))
            if gj:
                break
        if not gj:
            print(f"  micro-regioni {regione}: non scaricate")
            continue
        print(f"  micro-regioni {regione}: {len(gj.get('features', []))} poligoni")
        feature.extend(gj.get("features", []))
    if not feature:
        print("  ATTENZIONE: nessuna micro-regione EAWS. I bollettini valanghe")
        print("  non potranno essere associati alle gite.")
        return 0
    b = settings.bbox
    riquadro = box(b[0] - 0.2, b[1] - 0.2, b[2] + 0.2, b[3] + 0.2)
    ritagliato = _ritaglia({"type": "FeatureCollection", "features": feature}, riquadro)
    with open(settings.eaws_regions_geojson, "w", encoding="utf-8") as f:
        json.dump(ritagliato, f)
    print(f"  micro-regioni tenute: {len(ritagliato['features'])}")
    return len(ritagliato["features"])


if __name__ == "__main__":
    if "--solo-archivio" in sys.argv:
        # I file ci sono gia' (arrivano dal repository): serve solo riempire
        # la tabella dei comuni.  E' quello che fa l'avvio su Railway.
        print(f"Comuni scritti in archivio: {popola_comuni()}")
        raise SystemExit(0)

    print("Confini comunali")
    comuni()
    print("\nMicro-regioni valanghe EAWS")
    micro_regioni_eaws()
    print("\nFatto. Ora puoi lanciare: python scripts/importa.py")
