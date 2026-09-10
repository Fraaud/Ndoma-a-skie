"""Parcheggi, ripari e piole da OpenStreetMap.

  python scripts/importa_posti.py                 # tutto
  python scripts/importa_posti.py parcheggi       # una famiglia sola

Si lancia DOPO le gite: i parcheggi si tengono solo se stanno vicino a una
gita del catalogo, altrimenti si importerebbero tutti i parcheggi di Cuneo.

Non serve rilanciarlo spesso - un parcheggio non si sposta - ma vale la
pena una volta al mese: in OSM la `capacity` viene aggiunta col tempo, e
quello e' il campo che ci interessa di piu'.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import posti  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import init_db, session_scope  # noqa: E402
from app.geo import indice_comuni  # noqa: E402
from app.models import Posto  # noqa: E402
from importers import posti as importatore  # noqa: E402


def principale(quali: list[str]) -> int:
    init_db()
    if not indice_comuni().disponibile:
        print("! confini comunali assenti: le piole resterebbero senza comune, "
              "e senza comune non si trovano lungo il ritorno.", file=sys.stderr)

    print(f"bbox: {settings.bbox}", file=sys.stderr)
    esito = asyncio.run(importatore.importa(quali or None))

    with session_scope() as db:
        totale = db.query(Posto).count()
        con_capienza = (db.query(Posto)
                        .filter(Posto.tipo == "parcheggio",
                                Posto.capienza.isnot(None)).count())
        per_tipo = {t: db.query(Posto).filter(Posto.tipo == t).count()
                    for t in ("parcheggio", "riparo", "piola")}

    print(f"\nin archivio: {totale} posti "
          f"({per_tipo['parcheggio']} parcheggi, {per_tipo['riparo']} ripari, "
          f"{per_tipo['piola']} piole)", file=sys.stderr)
    print(f"parcheggi con la capienza dichiarata: {con_capienza}",
          file=sys.stderr)
    print(posti.ATTRIBUZIONE, file=sys.stderr)
    # sullo stdout solo il numero, che gli script d'avvio leggono
    return esito["nuovi"] + esito["aggiornati"]


if __name__ == "__main__":
    print(principale(sys.argv[1:]))
