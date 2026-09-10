"""Aggiornamento notturno di meteo, bollettini e punteggi.

Sta qui e non dentro lo script perche' lo chiamano in due: scripts/aggiorna.py
quando lo lanci a mano o da cron, e il bot una volta al giorno quando l'app
gira su una piattaforma dove non puoi mettere un cron separato (Railway monta
il volume del database su un servizio solo, quindi tutto vive li' dentro).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import time

from sqlalchemy.orm import Session

from app import passaggi, schede, simulazione
from app.models import Condizioni, Gita


async def aggiorna_tutto(db: Session, pausa: float = 0.25, verboso: bool = True) -> dict:
    # PRIMA di ogni altra cosa, e prima del ramo della simulazione: le
    # uscite con la data passata si chiudono. Restavano "aperta" per sempre
    # - invisibili nell'elenco (che parte da oggi) ma vive nel profilo di
    # chi le aveva pubblicate. Se questa riga stesse sotto al `return` della
    # simulazione, con la simulazione accesa non girerebbe mai.
    if db is not None:
        try:
            chiuse = passaggi.chiudi_scadute(db)
            if chiuse and verboso:
                print(f"  {chiuse} uscite passate chiuse")
        except Exception as e:
            print(f"  chiusura delle uscite passate non riuscita: {e}")

    # Con la simulazione accesa si ricarica quella, non i dati di oggi:
    # altrimenti l'aggiornamento notturno la cancellerebbe ogni notte alle
    # quattro e la mattina l'app tornerebbe vuota senza che nessuno capisca
    # perche'. Si spegne togliendo SIMULAZIONE_INVERNO.
    if simulazione.attiva():
        return await simulazione.carica(db, pausa=pausa, verboso=verboso)

    gite = db.query(Gita).filter(Gita.attiva.is_(True)).all()
    inizio = time.time()
    if verboso:
        print(f"{dt.datetime.now():%Y-%m-%d %H:%M} - aggiorno {len(gite)} gite")

    conteggi = {"gite": len(gite), "meteo": 0, "bollettini": 0, "punteggi": 0}
    regioni_fatte: set[str] = set()

    for i, g in enumerate(gite, 1):
        try:
            if await schede.meteo_gita(db, g, forza=True):
                conteggi["meteo"] += 1
        except Exception as e:
            print(f"  meteo {g.nome}: {e}")
        # il bollettino e' per micro-regione, non per gita: uno solo per regione
        if g.eaws_region and g.eaws_region not in regioni_fatte:
            regioni_fatte.add(g.eaws_region)
            try:
                if await schede.bollettino_gita(db, g, forza=True):
                    conteggi["bollettini"] += 1
            except Exception as e:
                print(f"  bollettino {g.eaws_region}: {e}")
        try:
            conteggi["punteggi"] += await schede.aggiorna_condizioni(db, g)
        except Exception as e:
            print(f"  condizioni {g.nome}: {e}")
        await asyncio.sleep(pausa)
        if verboso and i % 25 == 0:
            print(f"  {i}/{len(gite)}")

    conteggi["rimossi"] = (
        db.query(Condizioni)
        .filter(Condizioni.giorno < dt.date.today())
        .delete(synchronize_session=False)
    )
    db.commit()
    conteggi["secondi"] = round(time.time() - inizio)

    if verboso:
        print(f"fatto in {conteggi['secondi']}s - meteo {conteggi['meteo']}, "
              f"bollettini {conteggi['bollettini']} su {len(regioni_fatte)} "
              f"micro-regioni, {conteggi['punteggi']} punteggi giornalieri "
              f"({conteggi['rimossi']} vecchi rimossi)")
    return conteggi
