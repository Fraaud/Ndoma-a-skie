"""API + mini app.  Avvio:  uvicorn app.main:app --reload"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app import notifiche as notifiche_srv
from app import schede
from app.auth import utente_corrente
from app.config import settings
from app.db import get_db, init_db
from app.geo import comune_di, distanza_km
from app.models import Comune, Condizioni, Gita, Match, Uscita, Utente
from app.services import match as match_srv
from app.services import routing as routing_srv
from app.services import valanghe as val_srv

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def _scalda_indici() -> None:
    """Carica i GeoJSON e costruisce gli indici spaziali all'avvio.

    Senza questo, il costo (secondi) lo paga la prima richiesta che ne ha
    bisogno - tipicamente la prima pubblicazione di un'uscita - che nel
    frattempo blocca il server e fa scadere la connessione del client.
    """
    from app.geo import indice_comuni, indice_eaws

    for nome, indice in (("comuni", indice_comuni()), ("micro-regioni", indice_eaws())):
        print(f"  indice {nome}: {'pronto' if indice.disponibile else 'ASSENTE'}")


@asynccontextmanager
async def _ciclo_vita(app: FastAPI):
    init_db()
    print("Preparo gli indici geografici...")
    await asyncio.to_thread(_scalda_indici)
    yield


app = FastAPI(title="Ndoma a skié", version="0.1.0", lifespan=_ciclo_vita)
# In valle si naviga con una tacca di segnale: le risposte JSON compresse
# arrivano molto prima, e il catalogo e' quasi tutto testo.
app.add_middleware(GZipMiddleware, minimum_size=800)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def home():
    """La pagina viene servita con un numero di versione appeso a JS e CSS.

    Il webview di Telegram tiene in cache in modo aggressivo: senza questo,
    dopo ogni modifica al codice continueresti a vedere la versione vecchia
    e a chiederti perche' la correzione non ha effetto.
    """
    with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as f:
        html = f.read()
    versione = int(max(
        os.path.getmtime(os.path.join(STATIC_DIR, n)) for n in ("app.js", "style.css")
    ))
    html = html.replace("/static/app.js", f"/static/app.js?v={versione}")
    html = html.replace("/static/style.css", f"/static/style.css?v={versione}")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.get("/api/config")
def config():
    return {
        "tile_url": settings.tile_url,
        "tile_attribution": settings.tile_attribution,
        "disclaimer": val_srv.DISCLAIMER,
        "bbox": settings.bbox,
    }


# ------------------------------------------------------------------ gite


@app.get("/api/gite")
def elenco_gite(
    q: str = "",
    valle: str = "",
    limite: int = Query(60, le=300),
    db: Session = Depends(get_db),
):
    query = db.query(Gita).filter(Gita.attiva.is_(True))
    if q:
        query = query.filter(or_(Gita.nome.ilike(f"%{q}%"), Gita.comune.ilike(f"%{q}%")))
    if valle:
        query = query.filter(Gita.valle == valle)
    gite = query.order_by(Gita.nome).limit(limite).all()
    return {"totale": query.count(), "gite": [schede.gita_dict(g) for g in gite]}


@app.get("/api/valli")
def elenco_valli(db: Session = Depends(get_db)):
    righe = (
        db.query(Gita.valle, func.count(Gita.id))
        .filter(Gita.valle.isnot(None), Gita.attiva.is_(True))
        .group_by(Gita.valle)
        .order_by(func.count(Gita.id).desc())
        .all()
    )
    return [{"valle": v, "gite": n} for v, n in righe if v]


@app.get("/api/gite/{gita_id}")
async def dettaglio_gita(gita_id: int, giorno: Optional[str] = None, db: Session = Depends(get_db)):
    g = db.get(Gita, gita_id)
    if not g:
        raise HTTPException(404, "gita non trovata")
    d = dt.date.fromisoformat(giorno) if giorno else dt.date.today()
    return await schede.scheda(db, g, d)


class NuovaGita(BaseModel):
    nome: str = Field(min_length=3, max_length=200)
    lat: float
    lon: float
    quota_min: Optional[int] = None
    quota_max: Optional[int] = None
    esposizione: Optional[str] = None
    difficolta: Optional[str] = None
    valle: Optional[str] = None


@app.post("/api/gite")
def crea_gita(dati: NuovaGita, u: Utente = Depends(utente_corrente), db: Session = Depends(get_db)):
    """Gita aggiunta da un utente: e' cosi' che il catalogo cresce."""
    c = comune_di(dati.lat, dati.lon) or {}
    from app.geo import regione_eaws_di

    g = Gita(
        nome=dati.nome.strip(),
        fonte="utente",
        fonte_id=f"u{u.id}-{int(dt.datetime.now().timestamp())}",
        lat=dati.lat, lon=dati.lon,
        quota_min=dati.quota_min, quota_max=dati.quota_max,
        esposizione=dati.esposizione, difficolta=dati.difficolta,
        valle=dati.valle,
        comune=c.get("nome"), istat=str(c["istat"]) if c.get("istat") else None,
        paese="FR" if dati.lon < 7.0 and (c.get("nome") is None) else "IT",
        eaws_region=regione_eaws_di(dati.lat, dati.lon),
        verificata=False,
    )
    db.add(g)
    db.commit()
    db.refresh(g)
    return schede.gita_dict(g)


@app.get("/api/weekend")
async def weekend(
    giorno: Optional[str] = None,
    limite: int = Query(12, le=40),
    db: Session = Depends(get_db),
):
    """Le gite del catalogo ordinate per qualita' della neve prevista.

    E' la funzione che rende l'app utile anche con zero utenti: si legge
    volentieri il giovedi' sera, e chi la legge poi trova i passaggi.
    """
    d = dt.date.fromisoformat(giorno) if giorno else _prossimo_sabato()

    # Lettura pura da tabella, ordinata e limitata: nessun calcolo, nessuna
    # chiamata esterna. I punteggi li scrive scripts/aggiorna.py.
    righe = (
        db.query(Condizioni, Gita)
        .join(Gita, Gita.id == Condizioni.gita_id)
        .filter(Condizioni.giorno == d, Gita.attiva.is_(True))
        .order_by(Condizioni.punteggio.desc())
        .limit(limite)
        .all()
    )
    risultati = [{
        "gita": schede.gita_dict(g),
        "powder": {
            "punteggio": c.punteggio,
            "etichetta": c.etichetta,
            "neve_24h_cm": c.neve_24h,
            "neve_72h_cm": c.neve_72h,
            "vento_max_kmh": c.vento_max,
            "fattori": [c.fattore] if c.fattore else [],
            "avviso_valanghe": c.avviso,
        },
        "valanghe_grado": c.grado_valanghe,
        "evidenziatore": c.evidenziatore or [],
    } for c, g in righe]

    return {
        "giorno": d.isoformat(),
        "risultati": risultati,
        "disclaimer": val_srv.DISCLAIMER,
        "suggerimento": None if risultati else
            "Nessun punteggio per questo giorno: lancia scripts/aggiorna.py",
    }


def _prossimo_sabato(oggi: dt.date | None = None) -> dt.date:
    oggi = oggi or dt.date.today()
    return oggi + dt.timedelta(days=(5 - oggi.weekday()) % 7)


# ---------------------------------------------------------------- comuni


@app.get("/api/comuni")
def cerca_comuni(q: str = "", limite: int = 12, db: Session = Depends(get_db)):
    if len(q) < 2:
        return []
    righe = (
        db.query(Comune)
        .filter(Comune.nome.ilike(f"{q}%"))
        .order_by(Comune.nome)
        .limit(limite)
        .all()
    )
    return [
        {"istat": c.istat, "nome": c.nome, "provincia": c.provincia, "lat": c.lat, "lon": c.lon}
        for c in righe
    ]


# --------------------------------------------------------------- profilo


class Profilo(BaseModel):
    comune_partenza: Optional[str] = None
    istat_partenza: Optional[str] = None
    ha_auto: bool = False
    posti_default: int = 3
    notifiche: bool = True


@app.get("/api/profilo")
def leggi_profilo(u: Utente = Depends(utente_corrente)):
    return {
        "tg_id": u.tg_id, "username": u.username, "nome": u.nome,
        "comune_partenza": u.comune_partenza, "istat_partenza": u.istat_partenza,
        "ha_auto": u.ha_auto, "posti_default": u.posti_default, "notifiche": u.notifiche,
    }


@app.put("/api/profilo")
def salva_profilo(
    p: Profilo, u: Utente = Depends(utente_corrente), db: Session = Depends(get_db)
):
    u.comune_partenza = p.comune_partenza
    u.istat_partenza = p.istat_partenza
    u.ha_auto = p.ha_auto
    u.posti_default = max(0, min(8, p.posti_default))
    u.notifiche = p.notifiche
    if p.istat_partenza:
        c = db.get(Comune, p.istat_partenza)
        if c:
            u.lat_partenza, u.lon_partenza = c.lat, c.lon
            u.comune_partenza = c.nome
    db.commit()
    return leggi_profilo(u)


# ---------------------------------------------------------------- uscite


class NuovaUscita(BaseModel):
    tipo: str  # OFFRO | CERCO | COMPAGNI
    gita_id: Optional[int] = None
    zona: Optional[str] = None
    data: str
    flessibilita: int = 0
    ora_partenza: Optional[str] = None
    istat_partenza: Optional[str] = None
    posti: int = 0
    note: Optional[str] = None


def _uscita_dict(db: Session, us: Uscita, con_match: bool = False) -> dict:
    g = db.get(Gita, us.gita_id) if us.gita_id else None
    a = db.get(Utente, us.autore_id)
    d = {
        "id": us.id, "tipo": us.tipo, "data": us.data.isoformat(),
        "flessibilita": us.flessibilita, "ora_partenza": us.ora_partenza,
        "comune_partenza": us.comune_partenza, "posti": us.posti,
        "note": us.note, "stato": us.stato, "zona": us.zona,
        "gita": schede.gita_dict(g) if g else None,
        "autore": {"nome": a.nome, "username": a.username} if a else None,
    }
    if con_match:
        d["match"] = [
            {"punteggio": round(m.punteggio, 1), "motivo": m.motivo,
             "uscita": _uscita_dict(db, altra)}
            for m, altra in match_srv.match_di(db, us)
        ]
    return d


@app.get("/api/uscite")
def elenco_uscite(
    da: Optional[str] = None,
    a: Optional[str] = None,
    tipo: Optional[str] = None,
    db: Session = Depends(get_db),
):
    d1 = dt.date.fromisoformat(da) if da else dt.date.today()
    d2 = dt.date.fromisoformat(a) if a else d1 + dt.timedelta(days=21)
    q = db.query(Uscita).filter(Uscita.stato == "aperta", Uscita.data >= d1, Uscita.data <= d2)
    if tipo:
        q = q.filter(Uscita.tipo == tipo.upper())
    uscite = q.order_by(Uscita.data, Uscita.ora_partenza).all()
    return [_uscita_dict(db, u) for u in uscite]


async def _dopo_pubblicazione(uscita_id: int) -> None:
    """Calcolo del percorso, match e notifiche: DOPO aver risposto al client.

    Sono le operazioni lente (routing, intersezioni geografiche, chiamate a
    Telegram). Tenerle dentro la richiesta faceva scadere la connessione e
    l'utente vedeva il pulsante 'Pubblica' non rispondere.
    """
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        us = db.get(Uscita, uscita_id)
        if not us:
            return
        if us.tipo == "OFFRO" and us.gita_id and us.istat_partenza and us.lat_partenza:
            gita = db.get(Gita, us.gita_id)
            try:
                await routing_srv.calcola_percorso(
                    db, us.istat_partenza, us.lat_partenza, us.lon_partenza, gita
                )
            except Exception as e:
                print(f"percorso non calcolato per l'uscita {uscita_id}: {e}")
        try:
            for m in match_srv.aggiorna_match(db, us):
                await _notifica_match(db, m)
        except Exception as e:
            print(f"match non calcolati per l'uscita {uscita_id}: {e}")
    finally:
        db.close()


@app.post("/api/uscite")
async def crea_uscita(
    dati: NuovaUscita,
    sfondo: BackgroundTasks,
    u: Utente = Depends(utente_corrente),
    db: Session = Depends(get_db),
):
    if dati.tipo not in ("OFFRO", "CERCO", "COMPAGNI"):
        raise HTTPException(400, "tipo non valido")
    if not dati.gita_id and not dati.zona:
        raise HTTPException(400, "serve una gita o almeno una zona")

    istat = dati.istat_partenza or u.istat_partenza
    comune = db.get(Comune, istat) if istat else None

    us = Uscita(
        autore_id=u.id,
        gita_id=dati.gita_id,
        zona=dati.zona,
        tipo=dati.tipo,
        data=dt.date.fromisoformat(dati.data),
        flessibilita=max(0, min(7, dati.flessibilita)),
        ora_partenza=dati.ora_partenza,
        istat_partenza=istat,
        comune_partenza=comune.nome if comune else u.comune_partenza,
        lat_partenza=comune.lat if comune else u.lat_partenza,
        lon_partenza=comune.lon if comune else u.lon_partenza,
        posti=dati.posti if dati.tipo == "OFFRO" else max(1, dati.posti),
        note=dati.note,
    )
    db.add(us)
    db.commit()
    db.refresh(us)

    # Si risponde subito: percorso, match e notifiche vanno in sottofondo.
    sfondo.add_task(_dopo_pubblicazione, us.id)
    return _uscita_dict(db, us)


@app.get("/api/uscite/{uscita_id}")
def dettaglio_uscita(uscita_id: int, db: Session = Depends(get_db)):
    us = db.get(Uscita, uscita_id)
    if not us:
        raise HTTPException(404, "uscita non trovata")
    return _uscita_dict(db, us, con_match=True)


@app.post("/api/uscite/{uscita_id}/chiudi")
def chiudi_uscita(
    uscita_id: int, u: Utente = Depends(utente_corrente), db: Session = Depends(get_db)
):
    us = db.get(Uscita, uscita_id)
    if not us:
        raise HTTPException(404, "uscita non trovata")
    if us.autore_id != u.id:
        raise HTTPException(403, "non e' la tua uscita")
    us.stato = "chiusa"
    db.commit()
    return {"ok": True}


@app.get("/api/mie")
def mie_uscite(u: Utente = Depends(utente_corrente), db: Session = Depends(get_db)):
    uscite = (
        db.query(Uscita)
        .filter(Uscita.autore_id == u.id)
        .order_by(Uscita.data.desc())
        .limit(30)
        .all()
    )
    return [_uscita_dict(db, x, con_match=True) for x in uscite]


@app.get("/api/percorso/{uscita_id}")
def percorso_uscita(uscita_id: int, db: Session = Depends(get_db)):
    from app.models import Percorso

    us = db.get(Uscita, uscita_id)
    if not us or not us.gita_id or not us.istat_partenza:
        raise HTTPException(404, "percorso non disponibile")
    p = db.query(Percorso).filter_by(istat_partenza=us.istat_partenza, gita_id=us.gita_id).one_or_none()
    if not p:
        raise HTTPException(404, "percorso non ancora calcolato")
    comuni = db.query(Comune).filter(Comune.istat.in_(p.comuni_istat or [])).all()
    ordinati = {c.istat: c.nome for c in comuni}
    return {
        "km": p.km, "minuti": p.minuti,
        "comuni": [ordinati.get(i, i) for i in (p.comuni_istat or [])],
        "geometria": p.geometria,
    }


# --------------------------------------------------------- notifiche bot


async def _notifica_match(db: Session, m: Match) -> None:
    """Notifica immediata. Se fallisce, il match resta con notificato=False
    e ci pensa il bot a ritentare: vedi app/notifiche.py."""
    await notifiche_srv.notifica_match(db, m)


@app.get("/api/salute")
def salute(db: Session = Depends(get_db)):
    from app.geo import indice_comuni, indice_eaws

    return {
        "gite": db.query(Gita).count(),
        "comuni": db.query(Comune).count(),
        "uscite_aperte": db.query(Uscita).filter(Uscita.stato == "aperta").count(),
        "geo_comuni": indice_comuni().disponibile,
        "geo_eaws": indice_eaws().disponibile,
        "ors_configurato": bool(settings.ors_api_key),
        "bot_configurato": bool(settings.telegram_bot_token),
    }
