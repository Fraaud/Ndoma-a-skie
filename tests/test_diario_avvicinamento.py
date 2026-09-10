"""Il diario privato e l'avvicinamento.

Sul diario il test che conta di piu' e' quello che verifica che NON si veda:
e' privato per scelta, non per dimenticanza. Un contatore di gite visibile
diventa in fretta una classifica, e una classifica in montagna spinge nella
direzione sbagliata.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import sys
import time
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Fatta, Gita, Percorso  # noqa: E402

TOKEN = "123456:TESTTOKEN"
IERI = (dt.date.today() - dt.timedelta(days=1)).isoformat()


def intestazione(tg_id: int, nome: str = "Test") -> dict:
    campi = {"auth_date": str(int(time.time())),
             "user": json.dumps({"id": tg_id, "first_name": nome})}
    dcs = "\n".join(f"{k}={campi[k]}" for k in sorted(campi))
    segreto = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    campi["hash"] = hmac.new(segreto, dcs.encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urlencode(campi)}


@pytest.fixture()
def gita_e_client():
    Base.metadata.drop_all(engine)
    init_db()
    s = SessionLocal()
    g = Gita(nome="Rocca La Meja", fonte="test", fonte_id="1", lat=44.42, lon=7.05)
    s.add(g)
    s.commit()
    gid = g.id
    s.close()
    return TestClient(app), gid


# ------------------------------------------------------------------ diario


def test_si_segna_e_si_rilegge(gita_e_client):
    c, gid = gita_e_client
    r = c.post("/api/fatte", headers=intestazione(3001),
               json={"gita_id": gid, "data": IERI, "nota": "neve trasformata"})
    assert r.status_code == 200, r.text

    d = c.get("/api/fatte", headers=intestazione(3001)).json()
    assert len(d) == 1
    assert d[0]["gita"]["nome"] == "Rocca La Meja"
    assert d[0]["nota"] == "neve trasformata"


def test_lo_stesso_giorno_aggiorna_la_nota_invece_di_duplicare(gita_e_client):
    c, gid = gita_e_client
    c.post("/api/fatte", headers=intestazione(3002),
           json={"gita_id": gid, "data": IERI, "nota": "prima"})
    r = c.post("/api/fatte", headers=intestazione(3002),
               json={"gita_id": gid, "data": IERI, "nota": "corretta"})
    assert r.json()["aggiornata"] is True
    d = c.get("/api/fatte", headers=intestazione(3002)).json()
    assert len(d) == 1 and d[0]["nota"] == "corretta"


def test_il_diario_di_uno_non_e_il_diario_di_un_altro(gita_e_client):
    """Il test piu' importante del file."""
    c, gid = gita_e_client
    c.post("/api/fatte", headers=intestazione(3003),
           json={"gita_id": gid, "data": IERI})
    assert c.get("/api/fatte", headers=intestazione(3003)).json() != []
    assert c.get("/api/fatte", headers=intestazione(3004)).json() == []


def test_il_diario_non_compare_accanto_al_nome(gita_e_client):
    """Nessuna traccia sulle uscite pubbliche ne' nel profilo pubblico."""
    c, gid = gita_e_client
    c.post("/api/fatte", headers=intestazione(3005),
           json={"gita_id": gid, "data": IERI})
    c.post("/api/uscite", headers=intestazione(3005), json={
        "tipo": "OFFRO", "gita_id": gid,
        "data": (dt.date.today() + dt.timedelta(days=2)).isoformat(), "posti": 2})

    autore = c.get("/api/uscite").json()[0]["autore"]
    assert "fatte" not in autore and "diario" not in autore
    # e nemmeno dentro il riassunto dell'esperienza
    assert "uscit" not in (autore.get("esperienza") or "").lower()


def test_non_si_puo_cancellare_il_diario_di_un_altro(gita_e_client):
    c, gid = gita_e_client
    fid = c.post("/api/fatte", headers=intestazione(3006),
                 json={"gita_id": gid, "data": IERI}).json()["id"]
    assert c.delete(f"/api/fatte/{fid}", headers=intestazione(3007)).status_code == 404
    assert c.delete(f"/api/fatte/{fid}", headers=intestazione(3006)).status_code == 200
    assert c.get("/api/fatte", headers=intestazione(3006)).json() == []


def test_non_si_segna_una_gita_nel_futuro(gita_e_client):
    c, gid = gita_e_client
    domani = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    r = c.post("/api/fatte", headers=intestazione(3008),
               json={"gita_id": gid, "data": domani})
    assert r.status_code == 400


# ----------------------------------------------------------- avvicinamento


def test_senza_comune_lo_dice_invece_di_tacere(gita_e_client):
    c, gid = gita_e_client
    d = c.get(f"/api/avvicinamento/{gid}", headers=intestazione(4001)).json()
    assert d["stato"] == "senza_comune"


def test_col_percorso_gia_in_cache_risponde_subito(gita_e_client):
    c, gid = gita_e_client
    c.put("/api/profilo", headers=intestazione(4002),
          json={"comune_partenza": "Cuneo", "istat_partenza": "004078"})

    s = SessionLocal()
    # il comune deve esistere in archivio perche' il profilo prenda le coordinate
    from app.models import Comune, Utente
    s.add(Comune(istat="004078", nome="Cuneo", provincia="Cuneo",
                 lat=44.39, lon=7.55))
    s.commit()
    c.put("/api/profilo", headers=intestazione(4002),
          json={"comune_partenza": "Cuneo", "istat_partenza": "004078"})
    u = s.query(Utente).filter_by(tg_id=4002).one()
    s.add(Percorso(istat_partenza="004078", gita_id=gid, km=54.0, minuti=71.0,
                   comuni_istat=["004078", "004003"]))
    s.add(Comune(istat="004003", nome="Acceglio", provincia="Cuneo",
                 lat=44.47, lon=6.99))
    s.commit()
    assert u.lat_partenza is not None
    s.close()

    d = c.get(f"/api/avvicinamento/{gid}", headers=intestazione(4002)).json()
    assert d["stato"] == "pronto"
    assert d["minuti"] == 71 and d["km"] == 54
    assert d["stimato"] is False
    assert "Acceglio" in d["comuni"]


def test_senza_chiave_di_routing_i_minuti_sono_assenti_e_dichiarati(gita_e_client):
    """Meglio dire 'non lo so' che dare una stima in linea d'aria: fra due
    valli il tempo in auto non ha niente a che vedere con la distanza."""
    c, gid = gita_e_client
    s = SessionLocal()
    from app.models import Comune
    s.add(Comune(istat="004120", nome="Morozzo", provincia="Cuneo",
                 lat=44.44, lon=7.68))
    s.commit()
    s.close()
    c.put("/api/profilo", headers=intestazione(4003),
          json={"comune_partenza": "Morozzo", "istat_partenza": "004120"})
    s = SessionLocal()
    s.add(Percorso(istat_partenza="004120", gita_id=gid, km=None, minuti=None,
                   comuni_istat=["004120"]))
    s.commit()
    s.close()

    d = c.get(f"/api/avvicinamento/{gid}", headers=intestazione(4003)).json()
    assert d["minuti"] is None
    assert d["stimato"] is True


def test_una_gita_che_non_esiste_da_404(gita_e_client):
    c, _ = gita_e_client
    assert c.get("/api/avvicinamento/99999", headers=intestazione(4004)).status_code == 404
