"""La simulazione d'inverno, e soprattutto: che si veda che e' una simulazione.

Il rischio di questa funzione e' tutto in una frase: un grado di pericolo
mostrato senza contesto e' indistinguibile da quello di oggi, e qualcuno
potrebbe usarlo per decidere una gita. Questi test tengono ferme le tre cose
che lo impediscono - l'etichetta sull'ente emittente, l'avviso in cima
all'app, e il fatto che del contenuto del bollettino non si tocchi niente.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import simulazione as sim  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def accesa(monkeypatch):
    monkeypatch.setattr(settings, "simulazione_giorno", "2026-02-14")
    return dt.date(2026, 2, 14)


# ------------------------------------------------------- accensione/spegnimento


def test_spenta_per_default(monkeypatch):
    monkeypatch.setattr(settings, "simulazione_giorno", "")
    assert sim.attiva() is False
    assert sim.giorno() is None
    assert sim.avviso_utente() is None


def test_si_accende_con_la_variabile(accesa):
    assert sim.attiva() is True
    assert sim.giorno() == accesa


def test_una_data_scritta_male_non_accende_niente(monkeypatch):
    """Meglio spenta che accesa a meta': un errore di battitura non deve
    lasciare l'app con dati simulati e senza l'avviso."""
    monkeypatch.setattr(settings, "simulazione_giorno", "14/02/2026")
    assert sim.attiva() is False
    assert sim.avviso_utente() is None


# ------------------------------------------------------------------ l'avviso


def test_lavviso_nomina_la_data_vera(accesa):
    a = sim.avviso_utente()
    assert a["attiva"] is True
    assert a["giorno"] == "2026-02-14"
    assert "14/02/2026" in a["testo"]
    assert "non di oggi" in a["testo"]
    assert "decidere una gita" in a["testo"]


def test_lavviso_arriva_allapp(accesa):
    """L'app lo prende da /api/config: se sparisce da li', sparisce dallo schermo."""
    c = TestClient(app).get("/api/config").json()
    assert c["simulazione"]["attiva"] is True
    assert "14/02/2026" in c["simulazione"]["testo"]


def test_senza_simulazione_lapp_non_mostra_niente(monkeypatch):
    monkeypatch.setattr(settings, "simulazione_giorno", "")
    assert TestClient(app).get("/api/config").json()["simulazione"] is None


# --------------------------------------------------------------- il contenuto


def test_del_bollettino_si_riscrive_solo_lente():
    """Il testo del bollettino e' quello dell'ente: non si tocca una parola."""
    from app.db import SessionLocal, init_db
    init_db()
    db = SessionLocal()
    originale = {
        "ente": "ARPA Piemonte", "grado_massimo": 3,
        "problemi": ["neve ventata"], "testo": "Lastroni da vento sui pendii nord.",
        "link": "https://bollettini.aineva.it/",
    }
    sim._scrivi_bollettini(db, {"IT-21-01": originale}, dt.date(2026, 2, 14))

    from app.models import CacheBollettino
    riga = db.query(CacheBollettino).filter_by(eaws_region="IT-21-01",
                                               giorno=dt.date.today()).one()
    salvato = riga.payload
    assert salvato["ente"] == "SIMULAZIONE - bollettino del 2026-02-14"
    assert salvato["grado_massimo"] == 3
    assert salvato["problemi"] == ["neve ventata"]
    assert salvato["testo"] == originale["testo"]
    assert originale["ente"] == "ARPA Piemonte"  # l'originale non si modifica
    db.close()


# ---------------------------------------------------------- spostamento orari


def test_gli_orari_si_spostano_ma_i_valori_no():
    dati = {"hourly": {
        "time": ["2026-02-14T00:00", "2026-02-14T01:00"],
        "snowfall": [1.5, 2.0],
    }}
    fuori = sim.sposta_nel_tempo(dati, dt.date(2026, 2, 14), dt.date(2026, 9, 12))
    assert fuori["hourly"]["time"] == ["2026-09-12T00:00", "2026-09-12T01:00"]
    assert fuori["hourly"]["snowfall"] == [1.5, 2.0]   # la neve resta quella vera


def test_il_riepilogo_giornaliero_si_ricava_se_manca():
    """L'archivio orario non lo restituisce, ma le schede lo leggono."""
    dati = {"hourly": {
        "time": [f"2026-02-14T{h:02d}:00" for h in range(3)],
        "temperature_2m": [-5.0, -3.0, -8.0],
        "snowfall": [1.0, 2.0, 0.5],
        "precipitation": [1.0, 2.0, 0.5],
    }}
    d = sim.sposta_nel_tempo(dati, dt.date(2026, 2, 14), dt.date(2026, 2, 14))["daily"]
    assert d["temperature_2m_min"] == [-8.0]
    assert d["temperature_2m_max"] == [-3.0]
    assert d["snowfall_sum"] == [3.5]


# ------------------------------------------------------------- controlli data


def test_una_data_futura_viene_respinta():
    domani = dt.date.today() + dt.timedelta(days=1)
    assert any("non e' un giorno passato" in a for a in sim.controlla_data(domani))


def test_un_giorno_destate_avvisa_che_non_ci_sara_neve():
    assert any("non e' un giorno d'inverno" in a
               for a in sim.controlla_data(dt.date(2025, 7, 15)))


def test_un_giorno_dinverno_vero_non_da_problemi():
    assert sim.controlla_data(dt.date(2026, 2, 14)) == []


# ------------------------------------------ l'aggiornamento notturno la tiene

def test_laggiornamento_notturno_ricarica_la_simulazione(accesa, monkeypatch):
    """Senza questo, alle 4:00 la simulazione veniva cancellata e la mattina
    l'app tornava vuota senza che niente lo spiegasse."""
    import asyncio

    from app import aggiornamento

    chiamate = []

    async def finta(db, pausa=0.2, verboso=True):
        chiamate.append("simulazione")
        return {"gite": 0, "meteo": 0, "bollettini": 0, "punteggi": 0}

    monkeypatch.setattr(aggiornamento.simulazione, "carica", finta)
    # db a None di proposito: con la simulazione accesa non si deve arrivare
    # a interrogare il database dei dati veri
    asyncio.run(aggiornamento.aggiorna_tutto(None, verboso=False))
    assert chiamate == ["simulazione"]


def test_spenta_laggiornamento_fa_il_lavoro_vero(monkeypatch):
    import asyncio

    from app import aggiornamento
    from app.db import SessionLocal, init_db

    monkeypatch.setattr(settings, "simulazione_giorno", "")

    async def non_deve_girare(*a, **k):
        raise AssertionError("simulazione caricata con la variabile spenta")

    monkeypatch.setattr(aggiornamento.simulazione, "carica", non_deve_girare)
    init_db()
    db = SessionLocal()
    try:
        c = asyncio.run(aggiornamento.aggiorna_tutto(db, pausa=0, verboso=False))
        assert "simulazione" not in c
    finally:
        db.close()


# ------------------------------- la simulazione accesa dopo, ad archivio pieno


def test_caricata_riconosce_i_dati_veri_da_quelli_simulati(accesa):
    """Il caso: la variabile si accende quando l'archivio e' gia' pieno.

    Il controllo "ci sono condizioni?" risponderebbe si' e l'avvio non
    farebbe niente: la simulazione comparirebbe solo dopo l'aggiornamento
    notturno, cioe' domani. Chi ha appena impostato la variabile si aspetta
    di vederla adesso.
    """
    import datetime as dt

    from app.db import SessionLocal, engine, init_db
    from app.models import Base, CacheBollettino

    Base.metadata.drop_all(engine)
    init_db()
    db = SessionLocal()
    try:
        # archivio pieno, ma di dati veri
        db.add(CacheBollettino(eaws_region="IT-21-01", giorno=dt.date.today(),
                               payload={"ente": "ARPA Piemonte", "grado_massimo": 3}))
        db.commit()
        assert sim.caricata(db) is False

        # ora arriva la simulazione
        sim._scrivi_bollettini(db, {"IT-21-02": {"ente": "ARPA Piemonte"}},
                               dt.date(2026, 2, 14))
        assert sim.caricata(db) is True
    finally:
        db.close()


def test_lavvio_sa_che_deve_ricaricare(accesa):
    """Lo script chiede 'conta simulazione' e deve poter avere 0 o 1."""
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "deploy", "avvio_railway.sh")
    with open(script, encoding="utf-8") as f:
        testo = f.read()
    assert "simulazione.caricata" in testo
    assert 'SIMULAZIONE_INVERNO:-' in testo, (
        "l'avvio deve guardare la variabile, non indovinare")
