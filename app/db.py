"""Sessione DB e inizializzazione."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import Base

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
    future=True,
)


if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _pragma_sqlite(dbapi_conn, _record):
        """Impostazioni che rendono SQLite adatto a piu' scritture in parallelo.

        Senza WAL, una scrittura blocca tutte le letture: mentre il cron
        notturno aggiorna i punteggi, chi apre l'app riceverebbe
        'database is locked'. Con WAL letture e scritture convivono.
        """
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")      # letture e scritture insieme
        cur.execute("PRAGMA synchronous=NORMAL")    # veloce e sicuro con WAL
        cur.execute("PRAGMA busy_timeout=8000")     # aspetta invece di fallire
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA cache_size=-32000")     # 32 MB di cache pagine
        cur.close()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def _allinea_colonne(motore=None) -> list[str]:
    """Aggiunge alle tabelle esistenti le colonne nuove del modello.

    create_all() crea le tabelle che mancano ma NON tocca quelle che ci sono
    gia': aggiungere un campo al modello e ridistribuire lascerebbe il
    database del volume indietro, e ogni lettura fallirebbe con 'no such
    column'. Qui si confronta il modello con la tabella vera e si aggiunge
    cio' che manca.

    Solo colonne facoltative, cioe' quelle che si possono aggiungere senza
    inventare un valore per le righe gia' scritte: e' anche l'unica cosa che
    SQLite accetta senza riscrivere la tabella. Una modifica piu' invasiva
    (rinominare, cambiare tipo) va fatta a mano e consapevolmente, non da uno
    script che gira a ogni avvio.
    """
    motore = motore or engine
    if motore.dialect.name != "sqlite":
        return []  # su un database vero si usano le migrazioni, non questo
    from sqlalchemy import inspect, text

    ispettore = inspect(motore)
    aggiunte = []
    with motore.begin() as conn:
        for tabella in Base.metadata.sorted_tables:
            if not ispettore.has_table(tabella.name):
                continue
            presenti = {c["name"] for c in ispettore.get_columns(tabella.name)}
            for col in tabella.columns:
                if col.name in presenti or not col.nullable:
                    continue
                tipo = col.type.compile(motore.dialect)
                conn.execute(text(
                    f'ALTER TABLE "{tabella.name}" ADD COLUMN "{col.name}" {tipo}'))
                aggiunte.append(f"{tabella.name}.{col.name}")
    for a in aggiunte:
        print(f"  database: aggiunta colonna {a}")
    return aggiunte


def init_db() -> None:
    Base.metadata.create_all(engine)
    _allinea_colonne()


@contextmanager
def session_scope() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_db() -> Iterator[Session]:
    """Dependency FastAPI."""
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
