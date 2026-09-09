"""Aggiornamento notturno di meteo, bollettini e punteggi.

Le API esterne si chiamano UNA VOLTA PER GITA, di notte, non a ogni apertura
dell'app: il venerdi' sera si collegano tutti insieme e con 200 gite si
sforerebbero i limiti gratuiti in pochi minuti.

    python scripts/aggiorna.py

Da mettere in cron su un server tradizionale:
  0 4 * * *  cd /percorso/ndoma-a-skie && ./venv/bin/python scripts/aggiorna.py >> data/cron.log 2>&1

Su Railway non serve: il bot lo fa da solo ogni notte (vedi app/bot.py).
Il lavoro vero sta in app/aggiornamento.py, cosi' i due percorsi eseguono
esattamente lo stesso codice.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.aggiornamento import aggiorna_tutto  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402


async def principale() -> None:
    init_db()
    db = SessionLocal()
    try:
        await aggiorna_tutto(db)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(principale())
