"""Carica a mano la giornata d'inverno simulata (vedi app/simulazione.py).

Normalmente non serve: se in ambiente c'e' SIMULAZIONE_INVERNO, la
simulazione la ricarica da sola l'aggiornamento notturno, e resta viva senza
che nessuno se ne debba ricordare. Questo script serve per due cose:
provare un'altra data al volo, e ripulire.

    python scripts/prova_inverno.py                      # la data dell'ambiente
    python scripts/prova_inverno.py --data 2026-01-20    # un'altra giornata
    python scripts/prova_inverno.py --solo-limone        # solo attorno a Limone
    python scripts/prova_inverno.py --pulisci            # via tutto

ATTENZIONE
----------
I dati caricati sono REALI ma di un ALTRO GIORNO. L'ente emittente del
bollettino viene riscritto in "SIMULAZIONE - bollettino del <data>", e
finche' SIMULAZIONE_INVERNO e' impostata l'app mostra una fascia fissa in
cima a ogni schermata. Se carichi una simulazione SENZA quella variabile,
la fascia non compare: fallo solo su un'installazione che stai guardando tu.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import simulazione  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.geo import distanza_km  # noqa: E402
from app.models import CacheBollettino, CacheMeteo, Condizioni, Gita  # noqa: E402

LIMONE = (44.2027, 7.5772)


async def principale(giorno: dt.date, solo_limone: bool, raggio: float) -> None:
    problemi = [a for a in simulazione.controlla_data(giorno) if "non e' un giorno passato" in a]
    if problemi:
        raise SystemExit(
            f"\n{problemi[0]}\nServe una giornata d'inverno vera da rigiocare,\n"
            "non una data futura:\n\n  python scripts/prova_inverno.py --data 2026-02-14\n")

    init_db()
    db = SessionLocal()
    gite = db.query(Gita).filter(Gita.attiva.is_(True)).all()
    if solo_limone:
        gite = [g for g in gite if distanza_km(g.lat, g.lon, *LIMONE) <= raggio]
    if not gite:
        print("Nessuna gita selezionata: alza --raggio, o importa il catalogo.")
        db.close()
        return

    c = await simulazione.carica(db, giorno, gite)

    if not c["meteo"]:
        print("\nNessun dato caricato: guarda gli errori qui sopra.")
        print("Se dicono 'out of allowed range', la data non e' passata.")
        db.close()
        return

    # SOLO le gite di questa passata: leggere tutta la tabella mostrerebbe
    # righe rimaste da prima, facendo credere che sia stato caricato qualcosa
    ids = [g.id for g in gite]
    bersaglio = simulazione.prossimo_sabato()
    migliori = (
        db.query(Condizioni, Gita).join(Gita, Gita.id == Condizioni.gita_id)
        .filter(Condizioni.giorno == bersaglio, Condizioni.gita_id.in_(ids))
        .order_by(Condizioni.neve_72h.desc()).limit(10).all()
    )
    print(f"\nSabato {bersaglio.strftime('%d/%m')}, prime dieci per neve caduta:")
    print("  neve 72h  grado  itinerario")
    for cond, g in migliori:
        grado = str(cond.grado_valanghe) if cond.grado_valanghe else "-"
        print(f"  {(cond.neve_72h or 0):>5.0f} cm  {grado:^5}  {g.nome[:44]}")

    if settings.simulazione_giorno:
        print("\nSIMULAZIONE_INVERNO e' impostata: l'app mostra la fascia dei dati "
              "di prova\ne l'aggiornamento notturno ricarica la simulazione da solo.")
    else:
        print("\nATTENZIONE: SIMULAZIONE_INVERNO non e' impostata, quindi l'app NON "
              "mostra\nla fascia dei dati di prova, e stanotte l'aggiornamento "
              "riportera' i dati veri.")
    print("Per tornare alla realta' subito:  python scripts/prova_inverno.py --pulisci")
    db.close()


def pulisci() -> None:
    init_db()
    db = SessionLocal()
    b = db.query(CacheBollettino).delete()
    m = db.query(CacheMeteo).delete()
    c = db.query(Condizioni).delete()
    db.commit()
    db.close()
    print(f"Rimossi {b} bollettini, {m} meteo, {c} giornate di condizioni.")
    if settings.simulazione_giorno:
        print("SIMULAZIONE_INVERNO e' ancora impostata: al prossimo aggiornamento "
              "la simulazione\ntorna. Togli la variabile d'ambiente, poi lancia "
              "scripts/aggiorna.py.")
    else:
        print("Rilancia scripts/aggiorna.py per riempire con i dati di oggi.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Carica a mano una giornata d'inverno vera")
    p.add_argument("--data", default=settings.simulazione_giorno or "2026-02-14",
                   help="giorno d'inverno GIA' PASSATO (default: SIMULAZIONE_INVERNO)")
    p.add_argument("--solo-limone", action="store_true",
                   help="solo le gite attorno a Limone, per fare presto")
    p.add_argument("--raggio", type=float, default=15.0, help="km attorno a Limone")
    p.add_argument("--pulisci", action="store_true", help="rimuove la simulazione")
    a = p.parse_args()

    if a.pulisci:
        pulisci()
    else:
        asyncio.run(principale(dt.date.fromisoformat(a.data), a.solo_limone, a.raggio))
