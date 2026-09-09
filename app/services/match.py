"""Match fra uscite.

Tre tipi di uscita:
  OFFRO    - ho l'auto e N posti per la gita X il giorno D
  CERCO    - mi serve un passaggio per la gita X il giorno D
  COMPAGNI - il giorno D voglio andare in zona Z, cerco compagnia
             (la gita puo' non essere ancora decisa: e' il caso d'uso che
              nessuna app di car sharing copre, ed e' meta' del traffico)

Il punteggio premia, in ordine: essere sulla strada, stessa gita, stessa data.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.geo import distanza_km
from app.models import Gita, Match, Percorso, Uscita

SOGLIA = 5.0


def _giorni(a: dt.date, b: dt.date) -> int:
    return abs((a - b).days)


def _percorso(db: Session, uscita: Uscita) -> Percorso | None:
    if not uscita.gita_id or not uscita.istat_partenza:
        return None
    return (
        db.query(Percorso)
        .filter_by(istat_partenza=uscita.istat_partenza, gita_id=uscita.gita_id)
        .one_or_none()
    )


def _distanza_dal_percorso(percorso: Percorso | None, lat: float | None, lon: float | None) -> float | None:
    if not percorso or not percorso.geometria or lat is None or lon is None:
        return None
    coords = percorso.geometria.get("coordinates") or []
    if not coords:
        return None
    return min(distanza_km(lat, lon, c[1], c[0]) for c in coords)


def _sulla_stessa_strada(db: Session, a: Uscita, b: Uscita, ga: Gita, gb: Gita) -> bool:
    """Due gite diverse sono compatibili solo se una sta sulla strada dell'altra:
    il comune di un attacco compare fra i comuni attraversati per raggiungere
    l'altro. E' l'unico criterio di vicinanza che abbia senso fra le montagne."""
    for uscita, altra_gita in ((a, gb), (b, ga)):
        p = _percorso(db, uscita)
        if p and altra_gita.istat and altra_gita.istat in (p.comuni_istat or []):
            return True
    return False


def valuta(db: Session, a: Uscita, b: Uscita) -> tuple[float, str] | None:
    """Punteggio di compatibilita' fra due uscite, o None se incompatibili."""
    if a.id == b.id or a.autore_id == b.autore_id:
        return None
    if a.stato != "aperta" or b.stato != "aperta":
        return None

    # combinazioni ammesse
    coppia = {a.tipo, b.tipo}
    if coppia == {"OFFRO", "CERCO"} or coppia == {"COMPAGNI"} or coppia == {"OFFRO", "COMPAGNI"} \
            or coppia == {"CERCO", "COMPAGNI"}:
        pass
    else:
        return None

    # data
    tolleranza = max(a.flessibilita, b.flessibilita)
    diff = _giorni(a.data, b.data)
    if diff > tolleranza:
        return None
    punti = 3.0 if diff == 0 else 2.0
    motivi = ["stessa data"] if diff == 0 else [f"date a {diff} giorno/i di distanza"]

    # destinazione
    if a.gita_id and b.gita_id and a.gita_id == b.gita_id:
        punti += 3.0
        motivi.append("stessa gita")
    else:
        ga = db.get(Gita, a.gita_id) if a.gita_id else None
        gb = db.get(Gita, b.gita_id) if b.gita_id else None
        valle_a = (ga.valle if ga else None) or a.zona
        valle_b = (gb.valle if gb else None) or b.zona
        if valle_a and valle_b and valle_a == valle_b:
            punti += 1.5
            motivi.append(f"stessa zona ({valle_a})")
        elif ga and gb and ga.istat and ga.istat == gb.istat:
            punti += 1.0
            motivi.append(f"attacchi nello stesso comune ({ga.comune})")
        elif ga and gb and _sulla_stessa_strada(db, a, b, ga, gb):
            punti += 1.0
            motivi.append("attacchi sulla stessa strada")
        else:
            # ATTENZIONE: qui NON si usa la distanza in linea d'aria.
            # In montagna due attacchi a 10 km possono stare su due valli
            # diverse e a 90 km di strada, perche' bisogna scendere a valle
            # e risalire. L'unica prossimita' che conta e' quella stradale.
            return None

    # corridoio: chi guida passa dal comune di chi cerca?
    autista = a if a.tipo == "OFFRO" else (b if b.tipo == "OFFRO" else None)
    passeggero = b if autista is a else a
    if autista is not None:
        if autista.posti <= 0:
            return None
        perc = _percorso(db, autista)
        if perc and passeggero.istat_partenza and passeggero.istat_partenza in (perc.comuni_istat or []):
            punti += 4.0
            motivi.append(f"{passeggero.comune_partenza} e' sulla strada")
        else:
            d = _distanza_dal_percorso(perc, passeggero.lat_partenza, passeggero.lon_partenza)
            if d is not None and d <= 8:
                punti += 2.5
                motivi.append(f"a {d:.0f} km dal percorso")
            elif d is not None and d <= 20:
                punti += 1.0
                motivi.append(f"deviazione di circa {d:.0f} km")
            elif a.istat_partenza and a.istat_partenza == b.istat_partenza:
                punti += 3.0
                motivi.append("stesso comune di partenza")
    else:
        if a.istat_partenza and a.istat_partenza == b.istat_partenza:
            punti += 2.0
            motivi.append("stesso comune di partenza")

    # ora di partenza
    if a.ora_partenza and b.ora_partenza:
        try:
            ha = int(a.ora_partenza.split(":")[0]) * 60 + int(a.ora_partenza.split(":")[1])
            hb = int(b.ora_partenza.split(":")[0]) * 60 + int(b.ora_partenza.split(":")[1])
            if abs(ha - hb) <= 45:
                punti += 0.5
                motivi.append("orari compatibili")
        except Exception:
            pass

    if punti < SOGLIA:
        return None
    return punti, "; ".join(motivi)


def candidati(db: Session, uscita: Uscita) -> list[Uscita]:
    tolleranza = max(uscita.flessibilita, 3)
    da = uscita.data - dt.timedelta(days=tolleranza)
    a = uscita.data + dt.timedelta(days=tolleranza)
    q = (
        db.query(Uscita)
        .filter(Uscita.id != uscita.id)
        .filter(Uscita.stato == "aperta")
        .filter(Uscita.data >= da, Uscita.data <= a)
        .filter(Uscita.autore_id != uscita.autore_id)
    )
    if uscita.tipo == "OFFRO":
        q = q.filter(or_(Uscita.tipo == "CERCO", Uscita.tipo == "COMPAGNI"))
    elif uscita.tipo == "CERCO":
        q = q.filter(or_(Uscita.tipo == "OFFRO", Uscita.tipo == "COMPAGNI"))
    return q.all()


def aggiorna_match(db: Session, uscita: Uscita) -> list[Match]:
    """Ricalcola i match per una uscita. Restituisce i match NUOVI (da notificare)."""
    nuovi: list[Match] = []
    for altra in candidati(db, uscita):
        esito = valuta(db, uscita, altra)
        if not esito:
            continue
        punteggio, motivo = esito
        a_id, b_id = sorted((uscita.id, altra.id))
        esistente = db.query(Match).filter_by(uscita_a_id=a_id, uscita_b_id=b_id).one_or_none()
        if esistente:
            esistente.punteggio = punteggio
            esistente.motivo = motivo
            continue
        m = Match(uscita_a_id=a_id, uscita_b_id=b_id, punteggio=punteggio, motivo=motivo)
        db.add(m)
        nuovi.append(m)
    db.commit()
    return nuovi


def match_di(db: Session, uscita: Uscita) -> list[tuple[Match, Uscita]]:
    ms = (
        db.query(Match)
        .filter(or_(Match.uscita_a_id == uscita.id, Match.uscita_b_id == uscita.id))
        .order_by(Match.punteggio.desc())
        .all()
    )
    out = []
    for m in ms:
        altro_id = m.uscita_b_id if m.uscita_a_id == uscita.id else m.uscita_a_id
        altra = db.get(Uscita, altro_id)
        if altra and altra.stato == "aperta":
            out.append((m, altra))
    return out
