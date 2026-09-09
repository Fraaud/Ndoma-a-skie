"""Composizione della scheda gita: meteo, neve caduta, bollettino. Con cache.

Le API esterne si chiamano una volta per gita e per giorno, non a ogni
apertura dell'app: il venerdi' sera si collegano tutti insieme.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app.models import CacheBollettino, CacheMeteo, Condizioni, Gita
from app.services import meteo as meteo_srv
from app.services import neve as neve_srv
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
    """Meteo dalla cache. Scarica SOLO se forza=True.

    Le richieste web non devono mai dipendere da un servizio esterno: se
    Open-Meteo e' lento, a rallentare sarebbe l'app in mano all'utente.
    A scaricare ci pensa scripts/aggiorna.py, di notte.
    """
    oggi = dt.date.today()
    riga = db.query(CacheMeteo).filter_by(gita_id=gita.id, giorno=oggi).one_or_none()
    if not forza:
        return riga.payload if riga else None
    if riga and not _scaduta(riga.aggiornato_il, TTL_METEO):
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
    if not forza:                       # come per il meteo: niente rete nelle richieste
        return riga.payload if riga else None
    if riga and not _scaduta(riga.aggiornato_il, TTL_BOLLETTINO):
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


async def aggiorna_condizioni(db: Session, gita: Gita, giorni: int = 7) -> int:
    """Salva neve caduta e grado ufficiale per i prossimi `giorni`.

    Da chiamare da scripts/aggiorna.py, mai da una richiesta web.
    """
    dati_meteo = await meteo_gita(db, gita)
    if not dati_meteo:
        return 0
    boll = await bollettino_gita(db, gita)
    grado = (boll or {}).get("grado_massimo")

    oggi = dt.date.today()
    scritte = 0
    for i in range(giorni):
        giorno = oggi + dt.timedelta(days=i)
        n = neve_srv.nevicato(dati_meteo, giorno)
        if not n.get("disponibile"):
            continue
        riga = db.query(Condizioni).filter_by(gita_id=gita.id, giorno=giorno).one_or_none()
        if riga is None:
            riga = Condizioni(gita_id=gita.id, giorno=giorno)
            db.add(riga)
        riga.neve_24h = n["neve_24h_cm"]
        riga.neve_72h = n["neve_72h_cm"]
        riga.ore_da_ultima_neve = n["ore_da_ultima_neve"]
        riga.descrizione = n["descrizione"]
        riga.grado_valanghe = grado
        riga.aggiornato_il = dt.datetime.now(dt.timezone.utc)
        scritte += 1
    db.commit()
    return scritte


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
        out["neve"] = neve_srv.nevicato(dati_meteo, giorno)
        out["previsione_giorni"] = [
            meteo_srv.sintesi_giorno(dati_meteo, giorno + dt.timedelta(days=i)) for i in range(0, 6)
        ]
    if boll:
        # il bollettino intero, come e' stato scritto: nessun filtro, nessuna
        # evidenziazione di quali problemi riguarderebbero questa gita
        out["valanghe"] = {
            **boll,
            "link_ufficiale": val_srv.link_bollettino_ufficiale(gita.paese, gita.eaws_region),
        }
    else:
        out["valanghe"] = {
            "non_disponibile": True,
            "link_ufficiale": val_srv.link_bollettino_ufficiale(gita.paese, gita.eaws_region),
        }
    out["disclaimer"] = val_srv.DISCLAIMER
    return out
