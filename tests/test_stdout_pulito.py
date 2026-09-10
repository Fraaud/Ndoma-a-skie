"""Lo stdout degli script e' un dato, non un posto dove chiacchierare.

Il bug che ha reso necessario questo file e' costato un deploy intero.
`app/config.py` stampava su stdout l'avviso "DATABASE_URL e' un percorso
relativo"; lo script di avvio leggeva lo stdout di python per avere un
conteggio; il conteggio e' diventato "ATTENZIONE: ...\\n0"; e in bash

    [ "ATTENZIONE: ...
    0" -lt 100 ]

fallisce con "integer expression expected". Risultato: tre controlli andati a
vuoto in silenzio, comuni e catalogo vuoti, e nessun errore che spiegasse
perche'. L'avviso era giusto, era nel posto sbagliato.

Regola: tutto cio' che e' diagnostica va su stderr. Su stdout solo il
risultato. Questi test la tengono ferma.
"""
from __future__ import annotations

import os
import subprocess
import sys

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _python(codice: str, ambiente: dict) -> subprocess.CompletedProcess:
    amb = dict(os.environ)
    amb.pop("DATABASE_URL", None)
    amb.pop("DATA_DIR", None)
    amb.update(ambiente)
    return subprocess.run([sys.executable, "-c", codice], cwd=RADICE, env=amb,
                          capture_output=True, text=True, timeout=120)


CONTA = """
from app.db import SessionLocal, init_db
from app.models import Comune
init_db()
db = SessionLocal()
print(db.query(Comune).count())
db.close()
"""


def test_un_conteggio_resta_un_numero_anche_col_database_url_sbagliato(tmp_path):
    """Il caso esatto del deploy: DATABASE_URL relativo e DATA_DIR impostato."""
    r = _python(CONTA, {
        "DATA_DIR": str(tmp_path),
        "DATABASE_URL": "sqlite:///./data/ndoma.db",
    })
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().isdigit(), f"stdout inquinato: {r.stdout!r}"
    # e l'avviso non e' sparito: e' solo andato dove doveva
    assert "ATTENZIONE" in r.stderr
    assert "percorso relativo" in r.stderr


def test_lavviso_non_finisce_mai_su_stdout(tmp_path):
    r = _python("from app.config import settings", {
        "DATA_DIR": str(tmp_path),
        "DATABASE_URL": "sqlite:///./data/ndoma.db",
    })
    assert r.stdout == "", f"su stdout non ci deve andare niente: {r.stdout!r}"


def test_una_simulazione_scritta_male_avvisa_su_stderr(tmp_path):
    r = _python("from app import simulazione; print(simulazione.attiva())", {
        "DATA_DIR": str(tmp_path),
        "SIMULAZIONE_INVERNO": "14/02/2026",
    })
    assert r.stdout.strip() == "False"
    assert "SIMULAZIONE_INVERNO" in r.stderr


def test_una_colonna_aggiunta_allo_schema_non_sporca_il_conteggio(tmp_path):
    """init_db() puo' allineare le colonne, e lo dice: su stderr.

    Sta nello stesso flusso del conteggio, quindi valeva lo stesso rischio:
    dopo un cambio di schema il primo avvio avrebbe stampato
    "database: aggiunta colonna ..." davanti al numero.
    """
    codice = """
from sqlalchemy import create_engine, text
from app.db import _allinea_colonne
motore = create_engine("sqlite:///%s/vecchio.db", future=True)
with motore.begin() as c:
    c.execute(text("CREATE TABLE utenti (id INTEGER PRIMARY KEY, tg_id INTEGER)"))
_allinea_colonne(motore)
print(42)
""" % tmp_path
    r = _python(codice, {"DATA_DIR": str(tmp_path)})
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "42", f"stdout inquinato: {r.stdout!r}"
    assert "aggiunta colonna" in r.stderr


def test_lo_script_di_avvio_tiene_solo_le_cifre(tmp_path):
    """Seconda difesa, nello script: anche se un giorno qualcuno rimettesse
    una print su stdout, il conteggio deve restare un numero."""
    script = os.path.join(RADICE, "deploy", "avvio_railway.sh")
    with open(script, encoding="utf-8") as f:
        testo = f.read()
    assert "tail -n 1" in testo and "tr -cd '0-9'" in testo, (
        "la funzione conta() dello script di avvio deve filtrare l'output")


# --------------------------------------------- l'endpoint di manutenzione

def test_manutenzione_spenta_se_manca_il_token(monkeypatch):
    """Chi non la usa non deve avere una porta in piu' da difendere."""
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.delenv("TOKEN_MANUTENZIONE", raising=False)
    assert TestClient(app).post("/api/aggiorna").status_code == 404


def test_manutenzione_rifiuta_un_token_sbagliato(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setenv("TOKEN_MANUTENZIONE", "quello-giusto")
    c = TestClient(app)
    assert c.post("/api/aggiorna").status_code == 403
    assert c.post("/api/aggiorna",
                  headers={"X-Manutenzione": "quello-sbagliato"}).status_code == 403


def test_manutenzione_accetta_il_token_giusto(monkeypatch):
    from fastapi.testclient import TestClient

    from app import main as m

    monkeypatch.setenv("TOKEN_MANUTENZIONE", "quello-giusto")

    partito = []

    async def finto():
        partito.append(True)

    monkeypatch.setattr(m, "_aggiorna_in_sottofondo", finto)
    r = TestClient(m.app).post("/api/aggiorna",
                               headers={"X-Manutenzione": "quello-giusto"})
    assert r.status_code == 200
    assert r.json()["stato"] == "avviato"
    assert partito == [True]


def test_manutenzione_non_lancia_due_aggiornamenti_insieme(monkeypatch):
    """Sono centinaia di chiamate a un servizio gratuito: una alla volta."""
    from fastapi.testclient import TestClient

    from app import main as m

    monkeypatch.setenv("TOKEN_MANUTENZIONE", "quello-giusto")
    monkeypatch.setattr(m, "_aggiornamento_in_corso", True)
    r = TestClient(m.app).post("/api/aggiorna",
                               headers={"X-Manutenzione": "quello-giusto"})
    assert r.json()["stato"] == "gia_in_corso"


def test_il_token_non_va_nellindirizzo():
    """Un segreto in un URL finisce nei log, nella cronologia e nei referrer.
    Se un domani qualcuno lo spostasse in query string, questo test cade."""
    import inspect

    from app import main as m

    codice = inspect.getsource(m.aggiorna_adesso)
    assert "Header" in codice
    assert "Query" not in codice
