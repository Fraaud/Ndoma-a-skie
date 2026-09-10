"""Il database deve sopravvivere ai deploy, e se non lo fa deve dirlo.

Il caso da cui nasce questo file: DATABASE_URL con un percorso relativo
(sqlite:///./data/ndoma.db) e' giusto nel .env locale, e copiarlo nelle
variabili del servizio sembra la cosa naturale da fare. Dentro un container
invece punta al filesystem dell'immagine, che a ogni push viene ricostruito:
l'app riparte perfettamente ma vuota, e gli iscritti devono rimettere tutto.
Non c'e' nessun errore, perche' dal punto di vista del programma non e'
successo niente di sbagliato.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from app.config import _url_database  # noqa: E402


# ------------------------------------------------- scelta del percorso


def test_senza_variabile_il_database_va_nella_cartella_dati(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert _url_database("/data") == "sqlite:////data/ndoma.db"


def test_un_percorso_relativo_con_il_volume_finisce_sul_volume(monkeypatch):
    """E' il salvataggio: quel valore andrebbe perso a ogni deploy."""
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./data/ndoma.db")
    monkeypatch.setenv("DATA_DIR", "/data")
    assert _url_database("/data") == "sqlite:////data/ndoma.db"


def test_un_percorso_assoluto_si_rispetta(monkeypatch):
    """Quattro barre: chi l'ha scritto sapeva cosa faceva."""
    monkeypatch.setenv("DATABASE_URL", "sqlite:////data/altro.db")
    monkeypatch.setenv("DATA_DIR", "/data")
    assert _url_database("/data") == "sqlite:////data/altro.db"


def test_in_locale_il_percorso_relativo_resta_quello(monkeypatch):
    """Senza DATA_DIR non c'e' nessun volume e nessun deploy: va bene com'e'."""
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./data/ndoma.db")
    monkeypatch.delenv("DATA_DIR", raising=False)
    assert _url_database("/qualunque") == "sqlite:///./data/ndoma.db"


def test_un_database_vero_non_si_tocca(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://utente@host/ndoma")
    monkeypatch.setenv("DATA_DIR", "/data")
    assert _url_database("/data") == "postgresql+psycopg://utente@host/ndoma"


def test_il_nome_del_file_si_mantiene(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./dati/prova.db")
    monkeypatch.setenv("DATA_DIR", "/data")
    assert _url_database("/data") == "sqlite:////data/prova.db"


# ------------------------------------------------------- diagnosi


def test_stato_riconosce_un_database_su_server(monkeypatch):
    from app import archivio
    from app.config import settings

    monkeypatch.setattr(settings, "database_url", "postgresql://x/y")
    s = archivio.stato()
    assert s["tipo"] == "server" and s["persistente"] is True


def test_stato_dice_dove_sta_il_file_sqlite():
    from app import archivio

    s = archivio.stato()
    assert s["tipo"] == "sqlite"
    assert s["percorso"].endswith(".db")
    assert os.path.isabs(s["percorso"])


def test_in_locale_non_si_lamenta_del_volume(monkeypatch):
    """Sul portatile non c'e' nessun deploy che cancella: niente allarmi."""
    from app import archivio

    monkeypatch.delenv("DATA_DIR", raising=False)
    assert archivio.su_volume("/qualunque/cartella") is True


def test_dentro_un_container_la_cartella_del_codice_non_e_un_volume(monkeypatch):
    """Stesso dispositivo del codice = sta nell'immagine = si perde."""
    from app import archivio
    from app.config import BASE_DIR

    monkeypatch.setenv("DATA_DIR", os.path.join(BASE_DIR, "data"))
    assert archivio.su_volume(os.path.join(BASE_DIR, "data")) is False


def test_lavviso_compare_quando_serve(monkeypatch):
    from app import archivio
    from app.config import BASE_DIR, settings

    monkeypatch.setenv("DATA_DIR", os.path.join(BASE_DIR, "data"))
    monkeypatch.setattr(settings, "database_url",
                        f"sqlite:///{BASE_DIR}/data/ndoma.db")
    s = archivio.stato()
    assert s["persistente"] is False
    assert "si perdono iscritti" in s["avviso"]
    assert "si perde" in archivio.riga_di_avvio()
