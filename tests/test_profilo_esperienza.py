"""Il giro completo dell'esperienza: dal modulo all'archivio, e sulle schede.

Il punto che conta e' l'ultimo test: l'esperienza dichiarata deve arrivare
insieme al nome dentro le uscite, perche' il momento in cui serve e' quello
in cui si decide se scrivere a qualcuno per un passaggio.
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
from app.models import Base, Gita  # noqa: E402

TOKEN = "123456:TESTTOKEN"


def intestazione(tg_id: int, nome: str = "Test") -> dict:
    campi = {"auth_date": str(int(time.time())),
             "user": json.dumps({"id": tg_id, "first_name": nome})}
    dcs = "\n".join(f"{k}={campi[k]}" for k in sorted(campi))
    segreto = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    campi["hash"] = hmac.new(segreto, dcs.encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urlencode(campi)}


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    init_db()
    yield TestClient(app)


def test_si_salva_e_si_rilegge(client):
    r = client.put("/api/profilo", headers=intestazione(1001), json={
        "inverni": 6, "formazione": "corso", "difficolta_abituale": "BSA",
        "artva": True, "artva_prova": "stagione",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["inverni"] == 6 and d["artva"] is True
    assert "6 inverni" in d["esperienza"] and "corso valanghe" in d["esperienza"]
    assert d["esperienza_dichiarata"] is True

    assert client.get("/api/profilo", headers=intestazione(1001)).json()["formazione"] == "corso"


def test_il_profilo_porta_le_etichette_da_mostrare(client):
    """Il modulo costruisce i menu dal vocabolario del server, non da copie."""
    voc = client.get("/api/profilo", headers=intestazione(1002)).json()["vocabolario"]
    assert "corso" in voc["formazione"] and "BSA" in voc["difficolta"]
    assert set(voc["artva_prova"]) == {"mai", "vecchia", "stagione"}


def test_non_si_puo_scrivere_quello_che_si_vuole(client):
    d = client.put("/api/profilo", headers=intestazione(1003), json={
        "formazione": "campione del mondo", "difficolta_abituale": "ZZ",
        "inverni": 900,
    }).json()
    assert d["formazione"] is None
    assert d["difficolta_abituale"] is None
    assert d["inverni"] is None
    assert d["esperienza_dichiarata"] is False


def test_chi_non_dichiara_niente_non_sparisce(client):
    d = client.get("/api/profilo", headers=intestazione(1004)).json()
    assert d["esperienza"] == "esperienza non dichiarata"
    assert d["esperienza_dichiarata"] is False


def test_lesperienza_si_vede_sulle_uscite_degli_altri(client):
    """E' qui che serve davvero: accanto a chi offre o cerca un passaggio."""
    s = SessionLocal()
    g = Gita(nome="Cima di Test", fonte="test", fonte_id="1", lat=44.3, lon=7.4)
    s.add(g); s.commit()
    gita_id = g.id
    s.close()

    client.put("/api/profilo", headers=intestazione(2001), json={
        "comune_partenza": None, "inverni": 0, "formazione": "nessuna", "artva": False,
    })
    r = client.post("/api/uscite", headers=intestazione(2001), json={
        "tipo": "OFFRO", "gita_id": gita_id,
        "data": (dt.date.today() + dt.timedelta(days=3)).isoformat(),
        "posti": 3,
    })
    assert r.status_code == 200, r.text

    elenco = client.get("/api/uscite").json()
    assert elenco, "l'uscita appena pubblicata deve comparire"
    testo = elenco[0]["autore"]["esperienza"]
    assert "prima stagione" in testo
    assert "senza ARTVA" in testo
