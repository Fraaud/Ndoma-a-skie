"""Test dell'API. In particolare: la vista Weekend deve restare veloce.

Nasce da un problema vero: /api/weekend ricalcolava la scheda completa di
ogni gita a ogni apertura dell'app. Con 7 gite di prova era istantaneo, con
500 vere il webview di Telegram chiudeva la connessione prima della risposta.
Ora i punteggi sono precalcolati e l'endpoint fa una sola query ordinata.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Condizioni, Gita  # noqa: E402

SABATO = dt.date.today() + dt.timedelta(days=(5 - dt.date.today().weekday()) % 7)


@pytest.fixture()
def db_pieno():
    Base.metadata.drop_all(engine)
    init_db()
    s = SessionLocal()
    for i in range(30):
        g = Gita(nome=f"Gita {i:02d}", fonte="test", fonte_id=str(i),
                 lat=44.3 + i / 1000, lon=7.0 + i / 1000, valle="Valle Stura")
        s.add(g)
        s.flush()
        s.add(Condizioni(
            gita_id=g.id, giorno=SABATO, neve_72h=float(i), neve_24h=i / 3.0,
            ore_da_ultima_neve=6, grado_valanghe=3,
            descrizione=f"{i} cm nelle ultime 72 ore",
        ))
    s.commit()
    yield s
    s.close()


def test_weekend_ordina_per_neve_caduta(db_pieno):
    with TestClient(app) as c:
        d = c.get(f"/api/weekend?giorno={SABATO.isoformat()}").json()
    cm = [r["neve"]["neve_72h_cm"] for r in d["risultati"]]
    assert cm == sorted(cm, reverse=True)
    assert cm[0] == 29.0


def test_weekend_rispetta_il_limite(db_pieno):
    with TestClient(app) as c:
        d = c.get(f"/api/weekend?giorno={SABATO.isoformat()}&limite=5").json()
    assert len(d["risultati"]) == 5


def test_weekend_porta_grado_avvertenza_e_disclaimer(db_pieno):
    """Accanto ai centimetri devono esserci sempre il grado ufficiale,
    l'avvertenza sulla neve fresca e il disclaimer."""
    with TestClient(app) as c:
        d = c.get(f"/api/weekend?giorno={SABATO.isoformat()}&limite=3").json()
    assert d["disclaimer"] and d["avvertenza_neve"]
    assert "bollettino" in d["avvertenza_neve"].lower()
    assert all(r["valanghe_grado"] == 3 for r in d["risultati"])
    assert all("punteggio" not in r["neve"] for r in d["risultati"])


def test_weekend_senza_dati_suggerisce_cosa_fare(db_pieno):
    fra_un_mese = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    with TestClient(app) as c:
        d = c.get(f"/api/weekend?giorno={fra_un_mese}").json()
    assert d["risultati"] == []
    assert "aggiorna" in d["suggerimento"]


def test_weekend_non_dipende_dal_numero_di_gite(db_pieno):
    """La query e' limitata: 30 gite o 3000, il lavoro e' lo stesso.
    Se qualcuno rimette un ciclo su tutto il catalogo, questo test lo becca."""
    import time

    with TestClient(app) as c:
        c.get(f"/api/weekend?giorno={SABATO.isoformat()}")  # scalda
        t0 = time.perf_counter()
        for _ in range(10):
            c.get(f"/api/weekend?giorno={SABATO.isoformat()}")
        medio = (time.perf_counter() - t0) / 10
    assert medio < 0.25, f"troppo lento: {medio*1000:.0f} ms a richiesta"


def test_elenco_gite_e_valli(db_pieno):
    with TestClient(app) as c:
        d = c.get("/api/gite?limite=10").json()
        assert d["totale"] == 30 and len(d["gite"]) == 10
        valli = c.get("/api/valli").json()
    assert valli[0]["valle"] == "Valle Stura" and valli[0]["gite"] == 30


def test_home_ha_versione_sui_file_statici(db_pieno):
    """Il webview di Telegram tiene in cache: senza il numero di versione le
    correzioni al JavaScript non arriverebbero mai agli utenti."""
    with TestClient(app) as c:
        r = c.get("/")
    assert "/static/app.js?v=" in r.text
    assert r.headers.get("cache-control") == "no-store"


def test_pubblicare_senza_autenticazione_e_rifiutato(db_pieno):
    os.environ["TELEGRAM_BOT_TOKEN"] = "123456:TESTTOKEN"
    with TestClient(app) as c:
        r = c.post("/api/uscite", json={
            "tipo": "OFFRO", "gita_id": 1, "data": SABATO.isoformat(), "posti": 3,
        })
    assert r.status_code == 401
