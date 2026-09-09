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


def init_db() -> None:
    Base.metadata.create_all(engine)


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
