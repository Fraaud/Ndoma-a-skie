"""Test del match: e' il cuore del car sharing, va provato senza rete.

Scenario reale del Cuneese: uno parte da Cuneo e sale in Valle Stura;
un altro sta a Borgo San Dalmazzo, che e' proprio sulla strada; un terzo
sta a Saluzzo, che sulla strada non ci sta.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from app.db import SessionLocal, engine, init_db  # noqa: E402
from app.models import Base, Comune, Gita, Percorso, Uscita, Utente  # noqa: E402
from app.services import match as match_srv  # noqa: E402

SABATO = dt.date.today() + dt.timedelta(days=(5 - dt.date.today().weekday()) % 7 or 7)

# ISTAT fittizi ma coerenti come formato
CUNEO, BORGO, SALUZZO, PIETRAPORZIO = "004078", "004029", "004203", "004175"


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    init_db()
    s = SessionLocal()

    s.add_all([
        Comune(istat=CUNEO, nome="Cuneo", provincia="Cuneo", lat=44.39, lon=7.55),
        Comune(istat=BORGO, nome="Borgo San Dalmazzo", provincia="Cuneo", lat=44.33, lon=7.49),
        Comune(istat=SALUZZO, nome="Saluzzo", provincia="Cuneo", lat=44.64, lon=7.49),
        Comune(istat=PIETRAPORZIO, nome="Pietraporzio", provincia="Cuneo", lat=44.32, lon=7.03),
    ])
    gita = Gita(nome="Testa Malacosta", fonte="test", fonte_id="1",
                lat=44.32, lon=7.03, quota_min=1300, quota_max=2850,
                esposizione="N,NE", valle="Valle Stura", istat=PIETRAPORZIO)
    altra = Gita(nome="Rocca La Meja", fonte="test", fonte_id="2",
                 lat=44.42, lon=6.99, valle="Valle Maira")
    s.add_all([gita, altra])
    s.add_all([
        Utente(tg_id=1, username="autista", nome="Autista", istat_partenza=CUNEO,
               lat_partenza=44.39, lon_partenza=7.55, ha_auto=True),
        Utente(tg_id=2, username="borgo", nome="Quello di Borgo", istat_partenza=BORGO,
               lat_partenza=44.33, lon_partenza=7.49),
        Utente(tg_id=3, username="saluzzo", nome="Quello di Saluzzo", istat_partenza=SALUZZO,
               lat_partenza=44.64, lon_partenza=7.49),
    ])
    s.commit()

    # percorso Cuneo -> attacco, che passa da Borgo ma non da Saluzzo
    s.add(Percorso(
        istat_partenza=CUNEO, gita_id=gita.id, km=48, minuti=55,
        comuni_istat=[CUNEO, BORGO, PIETRAPORZIO],
        geometria={"type": "LineString",
                   "coordinates": [[7.55, 44.39], [7.49, 44.33], [7.03, 44.32]]},
    ))
    s.commit()
    yield s
    s.close()


def _uscita(db, tg_id, tipo, gita_id, giorno=None, posti=0, flex=0, istat=None):
    u = db.query(Utente).filter_by(tg_id=tg_id).one()
    us = Uscita(
        autore_id=u.id, gita_id=gita_id, tipo=tipo, data=giorno or SABATO,
        posti=posti, flessibilita=flex,
        istat_partenza=istat or u.istat_partenza,
        comune_partenza=(db.get(Comune, istat or u.istat_partenza).nome),
        lat_partenza=u.lat_partenza, lon_partenza=u.lon_partenza,
        ora_partenza="05:30",
    )
    db.add(us)
    db.commit()
    db.refresh(us)
    return us


def test_chi_e_sulla_strada_fa_match(db):
    gita = db.query(Gita).filter_by(nome="Testa Malacosta").one()
    offro = _uscita(db, 1, "OFFRO", gita.id, posti=3)
    cerco = _uscita(db, 2, "CERCO", gita.id, posti=1)

    esito = match_srv.valuta(db, offro, cerco)
    assert esito is not None
    punteggio, motivo = esito
    assert punteggio >= 10
    assert "sulla strada" in motivo


def test_chi_non_e_sulla_strada_prende_meno_punti(db):
    gita = db.query(Gita).filter_by(nome="Testa Malacosta").one()
    offro = _uscita(db, 1, "OFFRO", gita.id, posti=3)
    vicino = match_srv.valuta(db, offro, _uscita(db, 2, "CERCO", gita.id, posti=1))
    lontano = match_srv.valuta(db, offro, _uscita(db, 3, "CERCO", gita.id, posti=1))
    assert vicino[0] > (lontano[0] if lontano else 0)


def test_auto_piena_non_fa_match(db):
    gita = db.query(Gita).filter_by(nome="Testa Malacosta").one()
    offro = _uscita(db, 1, "OFFRO", gita.id, posti=0)
    cerco = _uscita(db, 2, "CERCO", gita.id, posti=1)
    assert match_srv.valuta(db, offro, cerco) is None


def test_date_diverse_senza_flessibilita_non_fanno_match(db):
    gita = db.query(Gita).filter_by(nome="Testa Malacosta").one()
    offro = _uscita(db, 1, "OFFRO", gita.id, posti=3)
    cerco = _uscita(db, 2, "CERCO", gita.id, posti=1, giorno=SABATO + dt.timedelta(days=1))
    assert match_srv.valuta(db, offro, cerco) is None


def test_la_flessibilita_riapre_il_match(db):
    gita = db.query(Gita).filter_by(nome="Testa Malacosta").one()
    offro = _uscita(db, 1, "OFFRO", gita.id, posti=3, flex=2)
    cerco = _uscita(db, 2, "CERCO", gita.id, posti=1, giorno=SABATO + dt.timedelta(days=1))
    esito = match_srv.valuta(db, offro, cerco)
    assert esito is not None and "distanza" in esito[1]


def test_gite_in_valli_diverse_non_fanno_match(db):
    """Rocca La Meja e' a 12 km in linea d'aria dalla Testa Malacosta, ma sta
    in un'altra valle: in mezzo c'e' una cresta e in auto sono 90 km.
    La distanza in linea d'aria non deve MAI generare un match."""
    stura = db.query(Gita).filter_by(nome="Testa Malacosta").one()
    maira = db.query(Gita).filter_by(nome="Rocca La Meja").one()
    offro = _uscita(db, 1, "OFFRO", stura.id, posti=3)
    cerco = _uscita(db, 2, "CERCO", maira.id, posti=1)
    assert match_srv.valuta(db, offro, cerco) is None


def test_gite_diverse_nella_stessa_valle_fanno_match(db):
    stura = db.query(Gita).filter_by(nome="Testa Malacosta").one()
    altra = Gita(nome="Monte Bersaio", fonte="test", fonte_id="3",
                 lat=44.30, lon=7.05, valle="Valle Stura", istat=PIETRAPORZIO)
    db.add(altra)
    db.commit()
    offro = _uscita(db, 1, "OFFRO", stura.id, posti=3)
    cerco = _uscita(db, 2, "CERCO", altra.id, posti=1)
    esito = match_srv.valuta(db, offro, cerco)
    assert esito is not None and "Valle Stura" in esito[1]


def test_non_si_fa_match_con_se_stessi(db):
    gita = db.query(Gita).filter_by(nome="Testa Malacosta").one()
    a = _uscita(db, 1, "OFFRO", gita.id, posti=3)
    b = _uscita(db, 1, "CERCO", gita.id, posti=1)
    assert match_srv.valuta(db, a, b) is None


def test_compagni_si_trovano_fra_loro(db):
    gita = db.query(Gita).filter_by(nome="Testa Malacosta").one()
    a = _uscita(db, 2, "COMPAGNI", gita.id, posti=1)
    b = _uscita(db, 3, "COMPAGNI", gita.id, posti=1)
    assert match_srv.valuta(db, a, b) is not None


def test_aggiorna_match_scrive_e_non_duplica(db):
    gita = db.query(Gita).filter_by(nome="Testa Malacosta").one()
    offro = _uscita(db, 1, "OFFRO", gita.id, posti=3)
    _uscita(db, 2, "CERCO", gita.id, posti=1)
    nuovi = match_srv.aggiorna_match(db, offro)
    assert len(nuovi) == 1
    assert match_srv.aggiorna_match(db, offro) == []   # gia' esistente
    assert len(match_srv.match_di(db, offro)) == 1
