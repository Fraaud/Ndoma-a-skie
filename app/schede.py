"""Composizione della scheda gita: meteo + powder + bollettino, con cache.

Le API esterne si chiamano una volta per gita e per giorno, non a ogni
apertura dell'app: il venerdi' sera si collegano tutti insieme.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app.models import CacheBollettino, CacheMeteo, Gita
from app.services import meteo as meteo_srv
from app.services import powder as powder_srv
from app.services import valanghe as val_srv

TTL_METEO = dt.timedelta(hours=6)
TTL_BOLLETTINO = dt.timedelta(hours=6)


def _scaduta(quando: dt.datetime | None, ttl: dt.timedelta) -> bool:
    if quando is None:
        return True
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc) - quando > ttl


async def meteo_gita(db: Session, gita: Gita, forza: bool = False) -> dict | None:
    oggi = dt.date.today()
    riga = db.query(CacheMeteo).filter_by(gita_id=gita.id, giorno=oggi).one_or_none()
    if riga and not forza and not _scaduta(riga.aggiornato_il, TTL_METEO):
        return riga.payload
    try:
        dati = await meteo_srv.previsioni(gita.lat, gita.lon, quota=gita.quota_min or gita.quota_max)
    except Exception:
        return riga.payload if riga else None
    if riga:
        riga.payload = dati
        riga.aggiornato_il = dt.datetime.now(dt.timezone.utc)
    else:
        db.add(CacheMeteo(gita_id=gita.id, giorno=oggi, payload=dati))
    db.commit()
    return dati


async def bollettino_gita(db: Session, gita: Gita, forza: bool = False) -> dict | None:
    if not gita.eaws_region:
        return None
    oggi = dt.date.today()
    riga = (
        db.query(CacheBollettino)
        .filter_by(eaws_region=gita.eaws_region, giorno=oggi)
        .one_or_none()
    )
    if riga and not forza and not _scaduta(riga.aggiornato_il, TTL_BOLLETTINO):
        return riga.payload
    try:
        tutti = await val_srv.scarica_bollettini(oggi)
    except Exception:
        return riga.payload if riga else None
    payload = tutti.get(gita.eaws_region)
    if payload is None:
        return riga.payload if riga else None
    if riga:
        riga.payload = payload
        riga.aggiornato_il = dt.datetime.now(dt.timezone.utc)
    else:
        db.add(CacheBollettino(eaws_region=gita.eaws_region, giorno=oggi,
                               payload=payload, fonte_url=payload.get("fonte_url")))
    db.commit()
    return payload


def gita_dict(g: Gita) -> dict:
    return {
        "id": g.id, "nome": g.nome, "lat": g.lat, "lon": g.lon,
        "quota_min": g.quota_min, "quota_max": g.quota_max, "dislivello": g.dislivello,
        "esposizione": g.esposizione, "difficolta": g.difficolta,
        "comune": g.comune, "valle": g.valle, "paese": g.paese,
        "fonte": g.fonte, "fonte_url": g.fonte_url, "licenza": g.licenza, "autori": g.autori,
        "eaws_region": g.eaws_region, "verificata": g.verificata,
    }


async def scheda(db: Session, gita: Gita, giorno: dt.date | None = None) -> dict:
    giorno = giorno or dt.date.today()
    dati_meteo = await meteo_gita(db, gita)
    boll = await bollettino_gita(db, gita)

    out = {"gita": gita_dict(gita), "giorno": giorno.isoformat()}
    if dati_meteo:
        out["meteo"] = meteo_srv.sintesi_giorno(dati_meteo, giorno)
        p = powder_srv.calcola(dati_meteo, giorno)
        p["etichetta"] = powder_srv.etichetta(p.get("punteggio"))
        out["powder"] = p
        out["previsione_giorni"] = [
            meteo_srv.sintesi_giorno(dati_meteo, giorno + dt.timedelta(days=i)) for i in range(0, 6)
        ]
    if boll:
        out["valanghe"] = {
            **boll,
            "evidenziatore": val_srv.evidenzia(gita, boll),
            "link_ufficiale": val_srv.link_bollettino_ufficiale(gita.paese, gita.eaws_region),
        }
    else:
        out["valanghe"] = {
            "non_disponibile": True,
            "link_ufficiale": val_srv.link_bollettino_ufficiale(gita.paese, gita.eaws_region),
        }
    out["disclaimer"] = val_srv.DISCLAIMER
    return out
