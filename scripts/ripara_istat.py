"""Riporta i codici ISTAT gia' salvati alla forma canonica a sei cifre.

Perche' serve
-------------
Il GeoJSON dei comuni porta lo stesso codice in due formati - "004078" e
4078 - e per un periodo l'indice spaziale leggeva il numero mentre la tabella
dei comuni leggeva la stringa. Siccome il confronto e' fra stringhe, "4078"
e "004078" non sono mai uguali, e la regola piu' importante del match ("il
passeggero e' SULLA STRADA di chi guida") non poteva scattare. Nessun errore
nei log: solo match che non arrivavano.

Ora la normalizzazione sta in app/geo.istat_a_sei, al punto d'ingresso. Questo
script sistema quello che era gia' finito in archivio. Si puo' rilanciare
quante volte si vuole: la seconda volta non trova piu' niente da fare.

    python scripts/ripara_istat.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import SessionLocal, init_db  # noqa: E402
from app.geo import istat_a_sei  # noqa: E402
from app.models import Gita, Percorso, Uscita, Utente  # noqa: E402


def ripara(db) -> dict:
    conteggi = {"gite": 0, "uscite": 0, "utenti": 0, "percorsi_buttati": 0}

    for modello, campo, chiave in ((Gita, "istat", "gite"),
                                   (Uscita, "istat_partenza", "uscite"),
                                   (Utente, "istat_partenza", "utenti")):
        for riga in db.query(modello).all():
            vecchio = getattr(riga, campo)
            nuovo = istat_a_sei(vecchio)
            if vecchio and nuovo != vecchio:
                setattr(riga, campo, nuovo)
                conteggi[chiave] += 1

    # I percorsi sono cache: quelli con le chiavi vecchie non si riparano, si
    # buttano. Si ricalcolano da soli alla prima apertura di una scheda, ed e'
    # meglio che riscriverli a mano rischiando di lasciarne uno a meta'.
    for p in db.query(Percorso).all():
        sbagliato = (istat_a_sei(p.istat_partenza) != p.istat_partenza
                     or any(istat_a_sei(x) != x for x in (p.comuni_istat or [])))
        if sbagliato:
            db.delete(p)
            conteggi["percorsi_buttati"] += 1

    db.commit()
    return conteggi


if __name__ == "__main__":
    init_db()
    db = SessionLocal()
    try:
        c = ripara(db)
    finally:
        db.close()
    if any(c.values()):
        print(f"Riparati: {c['gite']} gite, {c['uscite']} uscite, "
              f"{c['utenti']} utenti. Percorsi buttati (si ricalcolano): "
              f"{c['percorsi_buttati']}.")
    else:
        print("Niente da riparare: i codici ISTAT sono gia' tutti a sei cifre.")
