"""Le tracce degli itinerari, e le quote lungo la traccia.

  python scripts/importa_tracce.py            # scarica le tracce mancanti
  python scripts/importa_tracce.py --quote     # aggiunge le quote a chi non le ha
  python scripts/importa_tracce.py --quante 50 # solo le prime 50 (per provare)

Perche' esiste uno script separato invece di rifare l'import
------------------------------------------------------------
Le 980 gite in archivio sono state importate da una versione del codice che
leggeva la geometria, ne prendeva il primo punto e buttava il resto. La
traccia percio' non c'e', ma il suo indirizzo si': ogni gita conserva
`fonte_id`, cioe' l'identificativo su camptocamp. Questo script ripassa
quelle gite una per una e chiede alla fonte solo il dettaglio, senza
rifare la scansione delle aree - che sono ore.

E' interrompibile e si puo' rilanciare: salta quello che ha gia' fatto.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from app import tracce  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal, init_db, session_scope  # noqa: E402
from app.models import Gita, Traccia  # noqa: E402
from importers import camptocamp  # noqa: E402

# Camptocamp e' un servizio gratuito di un'associazione: fra due richieste
# si aspetta. 980 gite a un terzo di secondo sono sei minuti, e vanno bene.
PAUSA = 0.35
# Le quote passano dalla chiave ORS, che ha una quota giornaliera: si va
# piano e si accetta di finire domani.
PAUSA_QUOTE = 1.2


async def scarica_tracce(quante: int | None) -> tuple[int, int, int]:
    """Chiede a camptocamp il dettaglio delle gite senza traccia."""
    with session_scope() as db:
        senza = (db.query(Gita.id, Gita.fonte_id, Gita.nome)
                 .outerjoin(Traccia, Traccia.gita_id == Gita.id)
                 .filter(Gita.fonte == "camptocamp", Traccia.id.is_(None))
                 .limit(quante or 100000).all())
    print(f"gite senza traccia: {len(senza)}", file=sys.stderr)

    prese = solo_punto = errori = 0
    intestazioni = {"User-Agent": settings.user_agent, "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=45, headers=intestazioni,
                                 follow_redirects=True) as c:
        for i, (gita_id, fonte_id, nome) in enumerate(senza, 1):
            try:
                dett = await camptocamp._dettaglio(c, int(fonte_id))
            except Exception as e:
                print(f"  {nome}: {e}", file=sys.stderr)
                errori += 1
                await asyncio.sleep(PAUSA)
                continue
            punti = camptocamp.linea((dett or {}).get("geometry"))
            if not punti:
                # la fonte pubblica solo un punto: non e' un errore, e' un
                # limite del dato. Va detto, non aggirato.
                solo_punto += 1
            else:
                try:
                    with session_scope() as db:
                        g = db.get(Gita, gita_id)
                        tracce.salva(db, g, punti, "fonte",
                                     licenza=camptocamp.LICENZA, autori=g.autori)
                    prese += 1
                except Exception as e:
                    print(f"  {nome}: traccia scartata ({e})", file=sys.stderr)
                    errori += 1
            if i % 25 == 0:
                print(f"  {i}/{len(senza)} - {prese} tracce, "
                      f"{solo_punto} solo punto", file=sys.stderr)
            await asyncio.sleep(PAUSA)
    return prese, solo_punto, errori


async def aggiungi_quote(quante: int | None) -> tuple[int, int]:
    """Le quote lungo le tracce che ne sono senza."""
    from app.services import quote as quote_srv

    if not settings.ors_api_key:
        print("! ORS_API_KEY non impostata: le quote non si possono prendere",
              file=sys.stderr)
        return 0, 0

    with session_scope() as db:
        da_fare = [t.id for t in db.query(Traccia)
                   .filter(Traccia.quote_da.is_(None))
                   .limit(quante or 100000).all()]
    print(f"tracce senza quote: {len(da_fare)}", file=sys.stderr)

    fatte = falliti = 0
    for i, traccia_id in enumerate(da_fare, 1):
        db = SessionLocal()
        try:
            t = db.get(Traccia, traccia_id)
            if not t:
                continue
            esito = await quote_srv.quote_lungo(list(t.punti or []))
            if not esito:
                falliti += 1
            else:
                punti, sorgente = esito
                g = db.get(Gita, t.gita_id)
                tracce.salva(db, g, punti, t.origine, licenza=t.licenza,
                             autori=t.autori, caricata_da=t.caricata_da,
                             quote_da=sorgente)
                db.commit()
                fatte += 1
        except Exception as e:
            print(f"  traccia {traccia_id}: {e}", file=sys.stderr)
            falliti += 1
        finally:
            db.close()
        if i % 20 == 0:
            print(f"  {i}/{len(da_fare)} - {fatte} con quote", file=sys.stderr)
        # se il servizio ha smesso di rispondere non si insiste per mille volte
        if falliti >= 15 and fatte == 0:
            print("! quindici tentativi a vuoto: mi fermo qui", file=sys.stderr)
            break
        await asyncio.sleep(PAUSA_QUOTE)
    return fatte, falliti


def riassunto() -> int:
    with session_scope() as db:
        totale = db.query(Traccia).count()
        con_quote = db.query(Traccia).filter(Traccia.quote_da.isnot(None)).count()
        gite = db.query(Gita).count()
        per_origine = {o: db.query(Traccia).filter(Traccia.origine == o).count()
                       for o in tracce.ORIGINI}
    print(f"\nin archivio: {totale} tracce su {gite} gite "
          f"({con_quote} col profilo altimetrico)", file=sys.stderr)
    print("  per provenienza: "
          + ", ".join(f"{o} {n}" for o, n in per_origine.items() if n),
          file=sys.stderr)
    return totale


if __name__ == "__main__":
    init_db()
    argomenti = sys.argv[1:]
    quante = None
    if "--quante" in argomenti:
        quante = int(argomenti[argomenti.index("--quante") + 1])

    if "--quote" in argomenti:
        fatte, falliti = asyncio.run(aggiungi_quote(quante))
        print(f"quote: {fatte} tracce completate, {falliti} non riuscite",
              file=sys.stderr)
    else:
        prese, solo_punto, errori = asyncio.run(scarica_tracce(quante))
        print(f"tracce: {prese} scaricate, {solo_punto} gite hanno solo un "
              f"punto sulla fonte, {errori} errori", file=sys.stderr)

    # sullo stdout solo il numero, che gli script d'avvio leggono
    print(riassunto())
