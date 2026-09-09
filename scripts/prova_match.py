"""Perche' quel match non e' scattato.

Elenca le uscite aperte e, per ognuna, tutte le altre con il punteggio o il
motivo preciso dello scarto. Non tocca niente: legge e basta.

    python scripts/prova_match.py              # tutte le uscite aperte
    python scripts/prova_match.py 12           # solo l'uscita 12
    python scripts/prova_match.py 12 15        # confronta due uscite
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Gita, Percorso, Uscita, Utente  # noqa: E402
from app.services import match as match_srv  # noqa: E402

VERDE, ROSSO, GIALLO, FINE = "\033[92m", "\033[91m", "\033[93m", "\033[0m"


def riga(db, u: Uscita) -> str:
    g = db.get(Gita, u.gita_id) if u.gita_id else None
    a = db.get(Utente, u.autore_id)
    return (f"#{u.id} {u.tipo:<8} {u.data:%d/%m} "
            f"{(g.nome if g else (u.zona or '?'))[:34]:<36} "
            f"da {(u.comune_partenza or '?')[:16]:<18} "
            f"{a.nome if a else '?'}"
            + (f" ({u.posti} posti)" if u.tipo == 'OFFRO' else ""))


def diagnosi_dati(db, u: Uscita) -> list[str]:
    """Controlla i dati che il match usa: se manca qualcosa, e' quasi sempre
    il vero motivo per cui non e' scattato."""
    problemi = []
    if not u.istat_partenza:
        problemi.append("manca il comune di partenza (impostalo nel Profilo)")
    if not u.lat_partenza:
        problemi.append("manca la posizione del comune di partenza")
    if u.gita_id:
        g = db.get(Gita, u.gita_id)
        if g and not g.valle:
            problemi.append(f"la gita '{g.nome[:30]}' non ha la valle: puo' "
                            "combaciare solo con la stessa gita o con il "
                            "corridoio stradale")
        if u.istat_partenza and not db.query(Percorso).filter_by(
                istat_partenza=u.istat_partenza, gita_id=u.gita_id).first():
            problemi.append("percorso non ancora calcolato: senza, il criterio "
                            "dei comuni attraversati non puo' funzionare")
    if u.tipo == "OFFRO" and u.posti <= 0:
        problemi.append("zero posti dichiarati: non fara' mai match")
    return problemi


def confronta(db, a: Uscita, b: Uscita) -> None:
    e = match_srv.spiega(db, a, b)
    if e["scarto"]:
        print(f"  {ROSSO}no{FINE}  {riga(db, b)}")
        print(f"      {e['scarto']}")
    else:
        print(f"  {VERDE}si'{FINE} {e['punteggio']:>4}  {riga(db, b)}")
        print(f"      {'; '.join(e['motivi'])}")


def principale(argomenti: list[str]) -> None:
    init_db()
    db = SessionLocal()
    aperte = db.query(Uscita).filter(Uscita.stato == "aperta").order_by(Uscita.data).all()
    if not aperte:
        print("Nessuna uscita aperta.")
        return

    if len(argomenti) == 2:
        a, b = (db.get(Uscita, int(x)) for x in argomenti)
        if not a or not b:
            print("Uscita non trovata.")
            return
        print(riga(db, a)); confronta(db, a, b)
        db.close()
        return

    da_esaminare = ([db.get(Uscita, int(argomenti[0]))] if argomenti else aperte)
    for u in da_esaminare:
        if not u:
            continue
        print(f"\n{'=' * 78}\n{riga(db, u)}")
        for p in diagnosi_dati(db, u):
            print(f"  {GIALLO}!{FINE}  {p}")
        altre = [x for x in aperte if x.id != u.id]
        if not altre:
            print("  (nessun'altra uscita aperta con cui confrontarla)")
        for x in altre:
            confronta(db, u, x)
    db.close()


if __name__ == "__main__":
    principale(sys.argv[1:])
