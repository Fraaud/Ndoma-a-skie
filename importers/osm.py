"""Import da OpenStreetMap via Overpass (licenza ODbL, aperta).

Due cose utili:
  - itinerari taggati piste:type=skitour (in Italia sono pochi ma crescono)
  - parcheggi in quota, che sono i punti di attacco delle gite invernali

Nota ODbL: se ridistribuite dati derivati va citata OpenStreetMap. Lo facciamo
in ogni scheda tramite i campi fonte/licenza.
"""
from __future__ import annotations

import asyncio

import httpx

from app.config import settings
from app.db import session_scope
from app.geo import comune_di, regione_eaws_di
from app.models import Gita

LICENZA = "ODbL (OpenStreetMap)"

QUERY = """
[out:json][timeout:120];
(
  way["piste:type"="skitour"]["name"]({sud},{ovest},{nord},{est});
  relation["piste:type"="skitour"]["name"]({sud},{ovest},{nord},{est});
);
out center tags;
"""


async def importa() -> int:
    q = QUERY.format(
        ovest=settings.bbox[0], sud=settings.bbox[1],
        est=settings.bbox[2], nord=settings.bbox[3],
    )
    async with httpx.AsyncClient(timeout=180, headers={"User-Agent": settings.user_agent}) as c:
        r = await c.post(settings.url_overpass, data={"data": q})
        if r.status_code != 200:
            print(f"  osm: HTTP {r.status_code}")
            return 0
        elementi = r.json().get("elements", [])

    nuovi = 0
    for e in elementi:
        centro = e.get("center") or {}
        lat, lon = centro.get("lat"), centro.get("lon")
        if lat is None or lon is None:
            continue
        tags = e.get("tags", {})
        fonte_id = f"{e['type']}/{e['id']}"
        with session_scope() as db:
            if db.query(Gita).filter_by(fonte="osm", fonte_id=fonte_id).first():
                continue
            c_ = comune_di(lat, lon) or {}
            db.add(Gita(
                nome=tags.get("name", "")[:200],
                fonte="osm",
                fonte_id=fonte_id,
                fonte_url=f"https://www.openstreetmap.org/{e['type']}/{e['id']}",
                licenza=LICENZA,
                lat=lat, lon=lon,
                difficolta=tags.get("piste:difficulty"),
                comune=c_.get("nome"),
                istat=str(c_["istat"]) if c_.get("istat") else None,
                paese="IT" if c_.get("istat") else "FR",
                eaws_region=regione_eaws_di(lat, lon),
                verificata=False,
            ))
            nuovi += 1
    return nuovi


if __name__ == "__main__":
    print(f"osm: {asyncio.run(importa())} gite importate")
