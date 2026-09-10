"""API + mini app.  Avvio:  uvicorn app.main:app --reload"""
from __future__ import annotations

import asyncio
import datetime as dt
import hmac
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app import esperienza
from app import notifiche as notifiche_srv
from app import archivio, posti, schede, segnalazioni, simulazione
from app.auth import utente_corrente, utente_facoltativo
from app.config import settings
from app.db import get_db, init_db
from app.geo import comune_di, distanza_km
from app.models import (
    Comune, Condizioni, Fatta, Gita, Match, Posto, Segnalazione, Uscita, Utente,
)
from app.services import match as match_srv
from app.services import neve as neve_srv
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
    # Prima riga dei log a ogni avvio: se il database non e' sul volume si
    # legge qui, invece di scoprirlo quando gli iscritti sono spariti.
    print(archivio.riga_di_avvio())
    if (s := archivio.stato()).get("avviso"):
        print(f"ATTENZIONE: {s['avviso']}")
    if (g := simulazione.giorno()):
        print(f"SIMULAZIONE ATTIVA: dati del {g}, non di oggi "
              "(l'app lo mostra in cima a ogni schermata)")
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
        # se c'e', l'app mostra una fascia fissa in cima a ogni schermata:
        # un grado di pericolo senza contesto e' indistinguibile da quello
        # di oggi, e qualcuno potrebbe usarlo per decidere una gita
        "simulazione": simulazione.avviso_utente(),
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
    """Dove ha nevicato, con accanto il grado di pericolo ufficiale.

    Non e' una classifica delle gite migliori: e' l'elenco di dove e' caduta
    neve, un dato misurato. Il giudizio su dove convenga andare non lo da'
    l'app.
    """
    d = dt.date.fromisoformat(giorno) if giorno else _prossimo_sabato()

    # Lettura pura da tabella, ordinata e limitata: nessun calcolo, nessuna
    # chiamata esterna. I punteggi li scrive scripts/aggiorna.py.
    righe = (
        db.query(Condizioni, Gita)
        .join(Gita, Gita.id == Condizioni.gita_id)
        .filter(Condizioni.giorno == d, Gita.attiva.is_(True))
        .order_by(Condizioni.neve_72h.desc())
        .limit(limite)
        .all()
    )
    risultati = [{
        "gita": schede.gita_dict(g),
        "neve": {
            "ha_nevicato": (c.neve_72h or 0) >= 1.0,
            "neve_24h_cm": c.neve_24h,
            "neve_72h_cm": c.neve_72h,
            "ore_da_ultima_neve": c.ore_da_ultima_neve,
            "descrizione": c.descrizione,
        },
        "valanghe_grado": c.grado_valanghe,
    } for c, g in righe]

    return {
        "giorno": d.isoformat(),
        "risultati": risultati,
        "avvertenza_neve": neve_srv.AVVERTENZA_NEVE_FRESCA,
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

    # tutto facoltativo: chi non risponde resta "esperienza non dichiarata",
    # che e' un'informazione anche quella
    inverni: Optional[int] = None
    formazione: Optional[str] = None
    difficolta_abituale: Optional[str] = None
    artva: Optional[bool] = None
    artva_prova: Optional[str] = None


@app.get("/api/profilo")
def leggi_profilo(u: Utente = Depends(utente_corrente)):
    return {
        "tg_id": u.tg_id, "username": u.username, "nome": u.nome,
        "comune_partenza": u.comune_partenza, "istat_partenza": u.istat_partenza,
        "ha_auto": u.ha_auto, "posti_default": u.posti_default, "notifiche": u.notifiche,
        "inverni": u.inverni, "formazione": u.formazione,
        "difficolta_abituale": u.difficolta_abituale,
        "artva": u.artva, "artva_prova": u.artva_prova,
        "esperienza": esperienza.riassunto(u),
        "esperienza_dichiarata": esperienza.dichiarata(u),
        "vocabolario": {
            "formazione": esperienza.FORMAZIONE,
            "artva_prova": esperienza.ARTVA_PROVA,
            "difficolta": esperienza.DIFFICOLTA,
        },
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
    for campo, valore in esperienza.pulisci(p.model_dump()).items():
        setattr(u, campo, valore)
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
        # l'esperienza viaggia insieme al nome: dev'essere sotto gli occhi
        # nel momento in cui si decide di scrivere a qualcuno, non in una
        # scheda che nessuno apre
        "autore": {"nome": a.nome, "username": a.username,
                   "esperienza": esperienza.riassunto(a)} if a else None,
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


# ------------------------------------------------------- avvicinamento


@app.get("/api/avvicinamento/{gita_id}")
async def avvicinamento(
    gita_id: int,
    sfondo: BackgroundTasks,
    u: Utente = Depends(utente_corrente),
    db: Session = Depends(get_db),
):
    """Quanto ci metti ad arrivare all'attacco, e che paesi attraversi.

    E' lo stesso percorso stradale che serve al match, riusato per chi
    guarda una scheda: la domanda "quanto ci metto?" e "chi passa da casa
    mia?" sono la stessa domanda vista da due lati.

    Il calcolo e' pesante (interseca il percorso con 867 poligoni comunali)
    e va in sottofondo: la prima volta si risponde "in_calcolo" e l'app
    richiede tra qualche secondo, invece di tenere aperta una richiesta che
    il webview di Telegram chiuderebbe.
    """
    g = db.get(Gita, gita_id)
    if not g:
        raise HTTPException(404, "gita non trovata")
    if not u.istat_partenza or u.lat_partenza is None:
        return {"stato": "senza_comune"}

    from app.models import Percorso

    p = (db.query(Percorso)
         .filter_by(istat_partenza=u.istat_partenza, gita_id=g.id).one_or_none())
    if p is None:
        sfondo.add_task(_calcola_avvicinamento, u.istat_partenza,
                        u.lat_partenza, u.lon_partenza, g.id)
        return {"stato": "in_calcolo"}

    corridoio = list(p.comuni_istat or [])
    nomi = {c.istat: c.nome
            for c in db.query(Comune).filter(Comune.istat.in_(corridoio)).all()}

    # Le piole si cercano sul RITORNO: il corridoio si legge al contrario,
    # cosi' i paesi arrivano nell'ordine in cui li incontri tornando a casa.
    # Il paese della gita si salta: alle cinque di sera, a 1600 m, non c'e'
    # niente di aperto - la piola dove ci si ferma e' in fondovalle.
    ritorno = list(reversed(corridoio))
    piole = posti.in_comuni(db, ritorno, limite=8)
    return {
        "stato": "pronto",
        "da": u.comune_partenza,
        "minuti": round(p.minuti) if p.minuti else None,
        "km": round(p.km) if p.km else None,
        # Senza chiave di routing il percorso e' una retta: i minuti non
        # esistono e i paesi sono un'approssimazione. Va detto, non nascosto.
        "stimato": p.minuti is None,
        "comuni": [nomi.get(i, i) for i in corridoio],
        "piole": [{**posti.posto_dict(x), "comune": nomi.get(x.istat or "", "")}
                  for x in piole],
    }


async def _calcola_avvicinamento(istat: str, lat: float, lon: float, gita_id: int) -> None:
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        g = db.get(Gita, gita_id)
        if g:
            await routing_srv.calcola_percorso(db, istat, lat, lon, g)
    except Exception as e:
        print(f"avvicinamento {istat}->{gita_id} non calcolato: {e}")
    finally:
        db.close()


# --------------------------------------------------------- diario privato


class NuovaFatta(BaseModel):
    gita_id: int
    data: str
    nota: Optional[str] = Field(default=None, max_length=500)


@app.get("/api/fatte")
def elenco_fatte(u: Utente = Depends(utente_corrente), db: Session = Depends(get_db)):
    """Il diario di chi chiede, e di nessun altro.

    Non esiste un modo di leggere il diario di un'altra persona: non c'e'
    l'endpoint. E' voluto - vedi il commento sul modello Fatta.
    """
    righe = (db.query(Fatta).filter(Fatta.utente_id == u.id)
             .order_by(Fatta.data.desc()).limit(300).all())
    gite = {g.id: g for g in db.query(Gita).filter(
        Gita.id.in_([f.gita_id for f in righe] or [0])).all()}
    return [{
        "id": f.id, "data": f.data.isoformat(), "nota": f.nota,
        "gita": schede.gita_dict(gite[f.gita_id]) if f.gita_id in gite else None,
    } for f in righe]


@app.post("/api/fatte")
def segna_fatta(dati: NuovaFatta, u: Utente = Depends(utente_corrente),
                db: Session = Depends(get_db)):
    if not db.get(Gita, dati.gita_id):
        raise HTTPException(404, "gita non trovata")
    giorno = dt.date.fromisoformat(dati.data)
    if giorno > dt.date.today():
        raise HTTPException(400, "non puoi segnare una gita che non hai ancora fatto")
    esistente = (db.query(Fatta)
                 .filter_by(utente_id=u.id, gita_id=dati.gita_id, data=giorno)
                 .one_or_none())
    if esistente:
        esistente.nota = (dati.nota or "").strip() or None
        db.commit()
        return {"id": esistente.id, "aggiornata": True}
    f = Fatta(utente_id=u.id, gita_id=dati.gita_id, data=giorno,
              nota=(dati.nota or "").strip() or None)
    db.add(f)
    db.commit()
    return {"id": f.id, "aggiornata": False}


@app.delete("/api/fatte/{fatta_id}")
def cancella_fatta(fatta_id: int, u: Utente = Depends(utente_corrente),
                   db: Session = Depends(get_db)):
    # il filtro sull'utente e' la sicurezza: senza, con un id indovinato si
    # cancellerebbe il diario di un altro
    f = db.query(Fatta).filter_by(id=fatta_id, utente_id=u.id).one_or_none()
    if not f:
        raise HTTPException(404, "non trovata")
    db.delete(f)
    db.commit()
    return {"cancellata": True}


# ------------------------------------------------- parcheggi, ripari, piole


@app.get("/api/posti/{gita_id}")
def posti_della_gita(gita_id: int, db: Session = Depends(get_db)):
    """Cosa c'e' all'attacco: parcheggi (con la capienza) e ripari.

    I ripari li mandiamo anche quando nessuno li ha chiesti, e l'app li
    tiene da parte: servono in Emergenza, e in Emergenza il telefono e'
    probabilmente senza campo. Scaricarli quando la rete c'e' ancora e'
    l'unico modo di averli quando serve.
    """
    g = db.get(Gita, gita_id)
    if not g:
        raise HTTPException(404, "gita non trovata")

    parcheggi = posti.vicini(db, g.lat, g.lon, "parcheggio",
                             posti.RAGGIO_PARCHEGGIO, limite=5)
    ripari = posti.vicini(db, g.lat, g.lon, "riparo",
                          posti.RAGGIO_RIPARO, limite=6)
    return {
        "parcheggi": [posti.posto_dict(p, d) for p, d in parcheggi],
        "ripari": [posti.posto_dict(p, d) for p, d in ripari],
        "attribuzione": posti.ATTRIBUZIONE,
        # le distanze sono in linea d'aria: in montagna la strada e' sempre
        # piu' lunga, e va detto invece di far credere il contrario
        "avvertenza": "Distanze in linea d'aria. La capienza e' quella "
                      "dichiarata su OpenStreetMap: puo' essere vecchia, e "
                      "in inverno un parcheggio non spalato ha meno posti.",
    }


# ------------------------------------------------------- condizioni viste
#
# Il vocabolario e' chiuso e sta in app/segnalazioni.py: la ragione per cui
# e' chiuso e' scritta li' in cima, e vale la pena leggerla prima di
# aggiungere un'etichetta.


class NuovaSegnalazione(BaseModel):
    gita_id: int
    giorno: str
    neve: list[str] = Field(default_factory=list)
    traccia: Optional[str] = None
    accesso: list[str] = Field(default_factory=list)
    quota_cambio: Optional[int] = None
    nota: Optional[str] = None


def _segnalazione_dict(s: Segnalazione, autore: Utente | None,
                       oggi: dt.date | None = None) -> dict:
    g = segnalazioni.giorni_fa(s.giorno, oggi)
    return {
        "id": s.id,
        "giorno": s.giorno.isoformat(),
        "giorni_fa": g,
        "quando": segnalazioni.quando(g),
        # la neve cambia in una notte di vento: l'app lo dice invece di
        # presentare una segnalazione di dieci giorni come fosse di ieri
        "fresca": g <= segnalazioni.GIORNI_FRESCA,
        "neve": s.neve or [],
        "traccia": s.traccia,
        "accesso": s.accesso or [],
        "quota_cambio": s.quota_cambio,
        "nota": s.nota,
        "etichette": segnalazioni.etichette(s),
        "autore": {"nome": autore.nome, "username": autore.username,
                   "esperienza": esperienza.riassunto(autore)} if autore else None,
        "mia": False,
    }


@app.get("/api/segnalazioni/{gita_id}")
def elenco_segnalazioni(gita_id: int, db: Session = Depends(get_db),
                        io: Optional[Utente] = Depends(utente_facoltativo)):
    """Le condizioni viste sulla gita, dalla piu' recente.

    Si leggono anche da fuori Telegram (chi sfoglia dal browser vede la
    scheda intera), quindi qui l'autenticazione e' facoltativa: sapere chi
    guarda serve solo a marcare le sue, e se non si sa pazienza.
    """
    limite = dt.date.today() - dt.timedelta(days=segnalazioni.GIORNI_VALIDI)
    righe = (db.query(Segnalazione)
             .filter(Segnalazione.gita_id == gita_id, Segnalazione.giorno >= limite)
             .order_by(Segnalazione.giorno.desc(), Segnalazione.id.desc())
             .limit(20).all())
    autori = {u.id: u for u in db.query(Utente).filter(
        Utente.id.in_([s.utente_id for s in righe] or [0])).all()}

    fuori = []
    for s in righe:
        d = _segnalazione_dict(s, autori.get(s.utente_id))
        d["mia"] = bool(io and s.utente_id == io.id)
        fuori.append(d)
    return {"segnalazioni": fuori, "vocabolario": segnalazioni.VOCABOLARIO}


@app.post("/api/segnalazioni")
def scrivi_segnalazione(dati: NuovaSegnalazione,
                        u: Utente = Depends(utente_corrente),
                        db: Session = Depends(get_db)):
    if not db.get(Gita, dati.gita_id):
        raise HTTPException(404, "gita non trovata")
    giorno = dt.date.fromisoformat(dati.giorno)
    if giorno > dt.date.today():
        raise HTTPException(400, "non puoi raccontare un giorno che non c'e' ancora stato")
    if segnalazioni.giorni_fa(giorno) > segnalazioni.GIORNI_VALIDI:
        raise HTTPException(400, "troppo tempo fa: la neve di allora non c'e' piu'")

    pulita = segnalazioni.pulisci(dati.model_dump())
    if segnalazioni.vuota(pulita):
        raise HTTPException(400, "scegli almeno un'etichetta, o scrivi una nota")

    s = (db.query(Segnalazione)
         .filter_by(utente_id=u.id, gita_id=dati.gita_id, giorno=giorno).one_or_none())
    nuova = s is None
    if nuova:
        s = Segnalazione(utente_id=u.id, gita_id=dati.gita_id, giorno=giorno)
        db.add(s)
    for campo, valore in pulita.items():
        setattr(s, campo, valore)
    s.aggiornato_il = dt.datetime.now(dt.timezone.utc)
    db.commit()
    db.refresh(s)
    d = _segnalazione_dict(s, u)
    d["mia"] = True
    d["aggiornata"] = not nuova
    return d


@app.delete("/api/segnalazioni/{segnalazione_id}")
def cancella_segnalazione(segnalazione_id: int, u: Utente = Depends(utente_corrente),
                          db: Session = Depends(get_db)):
    # come per il diario, il filtro sull'utente E' la sicurezza
    s = (db.query(Segnalazione)
         .filter_by(id=segnalazione_id, utente_id=u.id).one_or_none())
    if not s:
        raise HTTPException(404, "non trovata")
    db.delete(s)
    db.commit()
    return {"cancellata": True}


# ------------------------------------------------------------ manutenzione

# Un aggiornamento alla volta: il lavoro dura minuti e fa centinaia di
# chiamate a Open-Meteo. Lanciarne due in parallelo vorrebbe dire raddoppiare
# il traffico verso un servizio gratuito, per riscrivere le stesse righe.
_aggiornamento_in_corso = False


@app.post("/api/aggiorna")
async def aggiorna_adesso(
    sfondo: BackgroundTasks,
    x_manutenzione: str = Header(default=""),
):
    """Forza l'aggiornamento di meteo, bollettini e condizioni.

    Perche' esiste: su Railway non c'e' una shell nel pannello (serve la CLI,
    quindi un computer) e il comando pre-deploy gira in un container a parte
    col volume SMONTATO, quindi non puo' scrivere il database. Senza questo
    endpoint, l'unico modo di ricaricare i dati e' aspettare il lavoro delle
    quattro del mattino - anche quando si e' appena cambiata una
    configurazione e si vorrebbe vedere l'effetto subito.

    Il token sta in un'INTESTAZIONE e non nell'indirizzo: un segreto in un
    URL finisce nei log del server, nella cronologia del browser e nei
    referrer. Se TOKEN_MANUTENZIONE non e' impostato l'endpoint non esiste,
    cosi' chi non lo usa non ha una porta in piu' da difendere.
    """
    atteso = os.getenv("TOKEN_MANUTENZIONE", "")
    if not atteso:
        raise HTTPException(404, "manutenzione non abilitata")
    # confronto a tempo costante: un == normale perde il segreto un carattere
    # alla volta, misurando quanto tempo ci mette a rispondere
    if not hmac.compare_digest(x_manutenzione, atteso):
        raise HTTPException(403, "token di manutenzione non valido")

    global _aggiornamento_in_corso
    if _aggiornamento_in_corso:
        return {"stato": "gia_in_corso"}

    sfondo.add_task(_aggiorna_in_sottofondo)
    g = simulazione.giorno()
    return {
        "stato": "avviato",
        "cosa": f"simulazione del {g}" if g else "dati di oggi",
        "come_seguirlo": "GET /api/salute, e la vista Weekend quando finisce",
    }


async def _aggiorna_in_sottofondo() -> None:
    from app.aggiornamento import aggiorna_tutto
    from app.db import SessionLocal

    global _aggiornamento_in_corso
    _aggiornamento_in_corso = True
    db = SessionLocal()
    try:
        c = await aggiorna_tutto(db, verboso=True)
        print(f"aggiornamento a richiesta: {c}")
    except Exception as e:
        print(f"aggiornamento a richiesta fallito: {e}")
    finally:
        _aggiornamento_in_corso = False
        db.close()


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
        "utenti": db.query(Utente).count(),
        "uscite_aperte": db.query(Uscita).filter(Uscita.stato == "aperta").count(),
        "geo_comuni": indice_comuni().disponibile,
        "geo_eaws": indice_eaws().disponibile,
        "ors_configurato": bool(settings.ors_api_key),
        "bot_configurato": bool(settings.telegram_bot_token),
        "simulazione": (g.isoformat() if (g := simulazione.giorno()) else None),
        # Se "persistente" e' falso, a ogni deploy si perdono utenti e
        # catalogo: e' la cosa piu' importante da poter controllare da fuori.
        "archivio": archivio.stato(),
    }
