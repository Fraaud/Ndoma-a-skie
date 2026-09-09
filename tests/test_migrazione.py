"""Il database sul volume deve reggere un campo nuovo senza essere buttato.

create_all() crea le tabelle che mancano ma non tocca quelle che esistono
gia'. Senza questo passaggio, aggiungere un campo al modello e ridistribuire
significherebbe: l'app parte, e poi ogni lettura degli utenti muore con
'no such column'. Su Railway il database sta su un volume e contiene le
persone iscritte: non e' una cosa che si puo' ricreare da zero.
"""
from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from app.db import _allinea_colonne


def _motore_vecchio(tmp_path):
    """Un database com'era prima: tabella utenti senza i campi esperienza."""
    motore = create_engine(f"sqlite:///{tmp_path}/vecchio.db", future=True)
    with motore.begin() as c:
        c.execute(text("""
            CREATE TABLE utenti (
                id INTEGER PRIMARY KEY,
                tg_id INTEGER,
                username VARCHAR(64),
                nome VARCHAR(120),
                comune_partenza VARCHAR(100),
                istat_partenza VARCHAR(10),
                lat_partenza FLOAT,
                lon_partenza FLOAT,
                ha_auto BOOLEAN,
                posti_default INTEGER,
                notifiche BOOLEAN,
                creato_il DATETIME
            )"""))
        c.execute(text("INSERT INTO utenti (id, tg_id, nome) VALUES (1, 42, 'Franco')"))
    return motore


def test_le_colonne_nuove_vengono_aggiunte(tmp_path):
    motore = _motore_vecchio(tmp_path)
    aggiunte = _allinea_colonne(motore)

    colonne = {c["name"] for c in inspect(motore).get_columns("utenti")}
    for campo in ("inverni", "formazione", "difficolta_abituale", "artva", "artva_prova"):
        assert campo in colonne, f"manca {campo}"
        assert f"utenti.{campo}" in aggiunte


def test_le_righe_gia_scritte_restano(tmp_path):
    """Nessuno deve sparire: si aggiunge una colonna, non si ricrea nulla."""
    motore = _motore_vecchio(tmp_path)
    _allinea_colonne(motore)
    with motore.begin() as c:
        riga = c.execute(text("SELECT nome, inverni FROM utenti WHERE tg_id=42")).one()
    assert riga.nome == "Franco"
    assert riga.inverni is None  # non dichiarato, che e' la verita'


def test_rilanciarlo_non_fa_niente(tmp_path):
    """Gira a ogni avvio: la seconda volta non deve avere nulla da fare."""
    motore = _motore_vecchio(tmp_path)
    assert _allinea_colonne(motore)          # la prima volta aggiunge
    assert _allinea_colonne(motore) == []    # la seconda no
