"""Popola il catalogo dalle fonti aperte.

  python scripts/importa.py            # tutte le fonti disponibili
  python scripts/importa.py camptocamp # una sola

Da lanciare DOPO scripts/setup_geo.py: senza i confini comunali e le
micro-regioni le gite verrebbero salvate senza comune ne' zona valanghe.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings  # noqa: E402
from app.db import init_db  # noqa: E402
from app.geo import indice_comuni, indice_eaws  # noqa: E402


async def principale(fonti: list[str]) -> None:
    init_db()
    if not indice_comuni().disponibile:
        print("! confini comunali assenti: lancia prima scripts/setup_geo.py")
    if not indice_eaws().disponibile:
        print("! micro-regioni EAWS assenti: i bollettini non verranno associati")

    totale = 0
    if "camptocamp" in fonti:
        from importers import camptocamp
        print("\n== Camptocamp ==")
        totale += await camptocamp.importa()
    if "skitour" in fonti:
        from importers import skitour
        print("\n== Skitour.fr ==")
        totale += await skitour.importa()
    if "osm" in fonti:
        from importers import osm
        print("\n== OpenStreetMap ==")
        totale += await osm.importa()
    if "posti" in fonti:
        # per ultimo, e non per caso: i parcheggi si tengono solo se stanno
        # vicino a una gita, quindi il catalogo deve esserci gia'
        from importers import posti
        print("\n== Parcheggi, ripari e piole (OSM) ==")
        esito = await posti.importa()
        print(f"  {esito['nuovi']} nuovi, {esito['aggiornati']} aggiornati")

    print(f"\nTotale importate: {totale}")
    print("Ricorda: le relazioni restano sulle fonti, noi linkiamo e attribuiamo.")


if __name__ == "__main__":
    scelte = sys.argv[1:] or ["camptocamp", "skitour", "osm", "posti"]
    print(f"bbox: {settings.bbox}")
    asyncio.run(principale(scelte))
