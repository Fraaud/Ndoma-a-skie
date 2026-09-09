"""Aggiornamento notturno di meteo e bollettini.

Le API esterne si chiamano UNA VOLTA PER GITA, di notte, non a ogni apertura
dell'app: il venerdi' sera si collegano tutti insieme e con 200 gite si
sforerebbero i limiti gratuiti in pochi minuti.

Da mettere in cron (esempio, ogni notte alle 4):
  0 4 * * *  cd /percorso/nduma && ./venv/bin/python scripts/aggiorna.py >> data/cron.log 2>&1
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import schede  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Gita  # noqa: E402


async def principale(pausa: float = 0.25) -> None:
    init_db()
    db = SessionLocal()
    gite = db.query(Gita).filter(Gita.attiva.is_(True)).all()
    print(f"{dt.datetime.now():%Y-%m-%d %H:%M} - aggiorno {len(gite)} gite")

    ok_meteo = ok_boll = 0
    regioni_fatte: set[str] = set()
    inizio = time.time()

    for i, g in enumerate(gite, 1):
        try:
            if await schede.meteo_gita(db, g, forza=True):
                ok_meteo += 1
        except Exception as e:
            print(f"  meteo {g.nome}: {e}")
        # il bollettino e' per micro-regione, non per gita: uno solo per regione
        if g.eaws_region and g.eaws_region not in regioni_fatte:
            regioni_fatte.add(g.eaws_region)
            try:
                if await schede.bollettino_gita(db, g, forza=True):
                    ok_boll += 1
            except Exception as e:
                print(f"  bollettino {g.eaws_region}: {e}")
        await asyncio.sleep(pausa)
        if i % 25 == 0:
            print(f"  {i}/{len(gite)}")

    db.close()
    print(f"fatto in {time.time() - inizio:.0f}s - meteo {ok_meteo}, "
          f"bollettini {ok_boll} su {len(regioni_fatte)} micro-regioni")


if __name__ == "__main__":
    asyncio.run(principale())
