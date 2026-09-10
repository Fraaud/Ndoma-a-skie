"""Un codice ISTAT, un formato solo.

Il bug che ha reso necessario questo file era invisibile: il GeoJSON dei
comuni porta lo stesso codice come "004078" e come 4078, l'indice spaziale
leggeva il numero e la tabella dei comuni la stringa. Confrontando stringhe,
"4078" e "004078" non sono mai uguali - quindi la regola che vale piu' di
tutte nel match, "il passeggero e' sulla strada di chi guida", non poteva
scattare mai. Nessun errore, nessun log: solo match che non arrivavano.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from app.db import SessionLocal, engine, init_db  # noqa: E402
from app.geo import istat_a_sei  # noqa: E402
from app.models import Base, Gita, Percorso, Uscita, Utente  # noqa: E402


# ------------------------------------------------------- la normalizzazione


@pytest.mark.parametrize("dentro,fuori", [
    (4078, "004078"),
    ("4078", "004078"),
    ("004078", "004078"),
    (1001, "001001"),
    ("1", "000001"),
])
def test_tutto_diventa_sei_cifre(dentro, fuori):
    assert istat_a_sei(dentro) == fuori


def test_i_due_formati_del_geojson_collassano_nello_stesso_codice():
    """E' il cuore della faccenda."""
    assert istat_a_sei("004078") == istat_a_sei(4078)


@pytest.mark.parametrize("vuoto", [None, ""])
def test_il_vuoto_resta_vuoto(vuoto):
    assert istat_a_sei(vuoto) is None


@pytest.mark.parametrize("altro", ["IT-21-01", "way/12345", "1234567"])
def test_quello_che_non_e_un_istat_non_si_tocca(altro):
    assert istat_a_sei(altro) == altro


def test_lindice_dei_comuni_restituisce_la_forma_canonica():
    from app.geo import comune_di

    c = comune_di(44.39, 7.55)          # Cuneo
    if not c:
        pytest.skip("geojson dei comuni non presente in questo ambiente")
    assert c["istat"] == "004078"
    assert len(c["istat"]) == 6


# ---------------------------------------------------------- la riparazione


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    init_db()
    s = SessionLocal()
    yield s
    s.close()


def test_ripara_i_codici_gia_salvati(db):
    from scripts.ripara_istat import ripara

    g = Gita(nome="Test", fonte="test", fonte_id="1", lat=44.4, lon=7.1, istat="4078")
    u = Utente(tg_id=5001, istat_partenza="4110")
    db.add_all([g, u])
    db.commit()
    db.add(Uscita(autore_id=u.id, gita_id=g.id, tipo="OFFRO",
                  data=dt.date.today(), istat_partenza="4003"))
    db.commit()

    c = ripara(db)
    assert c["gite"] == 1 and c["utenti"] == 1 and c["uscite"] == 1
    assert db.get(Gita, g.id).istat == "004078"
    assert db.get(Utente, u.id).istat_partenza == "004110"


def test_i_percorsi_con_le_chiavi_vecchie_si_buttano(db):
    """Sono cache: si ricalcolano. Ripararli a mano rischia di lasciarne
    uno con meta' codici vecchi e meta' nuovi, che e' peggio di niente."""
    from scripts.ripara_istat import ripara

    g = Gita(nome="Test", fonte="test", fonte_id="2", lat=44.4, lon=7.1)
    db.add(g)
    db.commit()
    db.add(Percorso(istat_partenza="4078", gita_id=g.id,
                    comuni_istat=["4078", "4003"]))
    db.add(Percorso(istat_partenza="004110", gita_id=g.id,
                    comuni_istat=["004110", "004078"]))
    db.commit()

    c = ripara(db)
    assert c["percorsi_buttati"] == 1
    restanti = db.query(Percorso).all()
    assert len(restanti) == 1
    assert restanti[0].istat_partenza == "004110"   # quello giusto resta


def test_rilanciarla_non_fa_niente(db):
    from scripts.ripara_istat import ripara

    g = Gita(nome="Test", fonte="test", fonte_id="3", lat=44.4, lon=7.1, istat="4078")
    db.add(g)
    db.commit()
    assert any(ripara(db).values())
    assert not any(ripara(db).values())


# ------------------------------------------------- la regola che si era rotta


def test_il_passeggero_sulla_strada_viene_riconosciuto(db):
    """Il test di regressione vero: con i due formati mescolati questo
    confronto era sempre falso, e il match da +4 punti non arrivava."""
    from app.services import match as match_srv

    g = Gita(nome="Rocca La Meja", fonte="test", fonte_id="9",
             lat=44.42, lon=7.05, valle="Valle Maira")
    autista = Utente(tg_id=6001, istat_partenza="004078", comune_partenza="Cuneo")
    # il passeggero abita in un paese che l'autista attraversa
    passeggero = Utente(tg_id=6002, istat_partenza="004003",
                        comune_partenza="Borgo San Dalmazzo")
    db.add_all([g, autista, passeggero])
    db.commit()

    quando = dt.date.today() + dt.timedelta(days=3)
    a = Uscita(autore_id=autista.id, gita_id=g.id, tipo="OFFRO", data=quando,
               istat_partenza="004078", comune_partenza="Cuneo", posti=3)
    b = Uscita(autore_id=passeggero.id, gita_id=g.id, tipo="CERCO", data=quando,
               istat_partenza="004003", comune_partenza="Borgo San Dalmazzo")
    db.add_all([a, b])
    db.commit()
    # il percorso dell'autista passa dal paese del passeggero
    db.add(Percorso(istat_partenza="004078", gita_id=g.id, km=54.0, minuti=71.0,
                    comuni_istat=["004078", "004003", "004110"]))
    db.commit()

    esito = match_srv.spiega(db, a, b)
    assert esito["punteggio"] >= match_srv.SOGLIA
    assert any("strada" in m.lower() or "passi" in m.lower() or "percorso" in m.lower()
               for m in esito["motivi"]), esito["motivi"]


def test_indice_e_tabella_dei_comuni_usano_lo_stesso_formato(db):
    """Il controllo incrociato che il bug richiedeva.

    Non basta che ognuno dei due sia coerente con se stesso: devono
    combaciare fra loro, perche' il match confronta un codice che arriva
    dall'indice spaziale con uno che arriva dalla tabella dei comuni.
    """
    from app.geo import comune_di
    from app.models import Comune
    from scripts.setup_geo import popola_comuni

    dallindice = comune_di(44.39, 7.55)      # Cuneo
    if not dallindice:
        pytest.skip("geojson dei comuni non presente in questo ambiente")

    popola_comuni()
    dalla_tabella = db.query(Comune).filter(Comune.nome == "Cuneo").one_or_none()
    assert dalla_tabella is not None, "Cuneo deve stare in archivio"
    assert dallindice["istat"] == dalla_tabella.istat
