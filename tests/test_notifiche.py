"""Test delle notifiche di match.

Nasce da un guasto vero: una modifica alla firma di una funzione ha fatto
fallire l'invio, il match e' rimasto salvato e nessuno e' stato avvisato -
per sempre, perche' non c'era nessun recupero.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from app import notifiche  # noqa: E402
from app.db import SessionLocal, engine, init_db  # noqa: E402
from app.models import Base, Gita, Match, Uscita, Utente  # noqa: E402

OGGI = dt.date.today()


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    init_db()
    s = SessionLocal()
    g = Gita(nome="Testa Malacosta", fonte="t", fonte_id="1", lat=44.34, lon=7.02)
    s.add(g)
    s.add_all([
        Utente(tg_id=111, username="autista", nome="Marco Rossi"),
        Utente(tg_id=222, nome="Giulia"),            # senza username, di proposito
    ])
    s.commit()
    a, b = s.query(Utente).all()
    ua = Uscita(autore_id=a.id, gita_id=g.id, tipo="OFFRO", data=OGGI, posti=3,
                comune_partenza="Cuneo", ora_partenza="05:30")
    ub = Uscita(autore_id=b.id, gita_id=g.id, tipo="CERCO", data=OGGI, posti=1,
                comune_partenza="Borgo San Dalmazzo")
    s.add_all([ua, ub])
    s.commit()
    s.add(Match(uscita_a_id=ua.id, uscita_b_id=ub.id, punteggio=10.5,
                motivo="stessa data; stessa gita"))
    s.commit()
    yield s
    s.close()


def _finto_invio(esiti: list):
    async def invia(chat_id, testo, tastiera=None):
        esiti.append({"chat_id": chat_id, "testo": testo, "tastiera": tastiera})
        return True
    return invia


def test_avvisa_entrambe_le_persone(db, monkeypatch):
    inviati: list = []
    monkeypatch.setattr(notifiche, "invia", _finto_invio(inviati))
    m = db.query(Match).one()
    assert asyncio.run(notifiche.notifica_match(db, m)) is True
    assert {x["chat_id"] for x in inviati} == {111, 222}
    assert m.notificato is True


def test_il_messaggio_contiene_il_necessario(db, monkeypatch):
    inviati: list = []
    monkeypatch.setattr(notifiche, "invia", _finto_invio(inviati))
    asyncio.run(notifica := notifiche.notifica_match(db, db.query(Match).one()))
    a_marco = next(x for x in inviati if x["chat_id"] == 111)
    assert "Giulia" in a_marco["testo"]
    assert "Testa Malacosta" in a_marco["testo"]
    assert "Borgo San Dalmazzo" in a_marco["testo"]
    # Giulia non ha username: il bottone deve usare comunque tg://
    assert a_marco["tastiera"]["inline_keyboard"][0][0]["url"] == "tg://user?id=222"


def test_se_l_invio_fallisce_il_match_resta_da_notificare(db, monkeypatch):
    async def invia_rotta(*a, **k):
        return False
    monkeypatch.setattr(notifiche, "invia", invia_rotta)
    m = db.query(Match).one()
    assert asyncio.run(notifiche.notifica_match(db, m)) is False
    assert m.notificato is False


def test_gli_arretrati_vengono_recuperati(db, monkeypatch):
    """Il caso che ci e' costato un pomeriggio: notifica fallita, match muto."""
    async def invia_rotta(*a, **k):
        return False
    monkeypatch.setattr(notifiche, "invia", invia_rotta)
    asyncio.run(notifiche.notifica_arretrati(db))
    assert db.query(Match).one().notificato is False

    inviati: list = []
    monkeypatch.setattr(notifiche, "invia", _finto_invio(inviati))
    assert asyncio.run(notifiche.notifica_arretrati(db)) == 1
    assert db.query(Match).one().notificato is True

    # gia' notificato: non lo rimanda
    assert asyncio.run(notifiche.notifica_arretrati(db)) == 0


def test_chi_ha_spento_le_notifiche_non_riceve_nulla(db, monkeypatch):
    inviati: list = []
    monkeypatch.setattr(notifiche, "invia", _finto_invio(inviati))
    db.query(Utente).filter_by(tg_id=222).one().notifiche = False
    db.commit()
    asyncio.run(notifiche.notifica_match(db, db.query(Match).one()))
    assert {x["chat_id"] for x in inviati} == {111}
