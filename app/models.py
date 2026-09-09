"""Modello dati.

Tre oggetti centrali:
  Gita    - un itinerario del catalogo (fonte aperta o inserito dagli utenti)
  Uscita  - "il giorno X vado alla gita Y", con ruolo OFFRO / CERCO / COMPAGNI
  Match   - due uscite compatibili
Il resto e' cache (meteo, bollettini, percorsi) e anagrafica.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, JSON,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Gita(Base):
    """Un itinerario. Nessun testo descrittivo di terzi: solo dati strutturati
    piu' il link alla fonte, che resta il posto dove si legge la relazione."""

    __tablename__ = "gite"
    __table_args__ = (UniqueConstraint("fonte", "fonte_id", name="uq_gita_fonte"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(200), index=True)
    fonte: Mapped[str] = mapped_column(String(30))          # camptocamp | skitour | osm | utente
    fonte_id: Mapped[str] = mapped_column(String(60))
    fonte_url: Mapped[Optional[str]] = mapped_column(String(400))
    licenza: Mapped[Optional[str]] = mapped_column(String(60))
    autori: Mapped[Optional[str]] = mapped_column(String(400))  # attribuzione richiesta da CC-BY-SA

    # Punto di attacco = dove si parcheggia. E' la coordinata che conta per tutto:
    # meteo, routing, comune, micro-regione valanghe.
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    lat_cima: Mapped[Optional[float]] = mapped_column(Float)
    lon_cima: Mapped[Optional[float]] = mapped_column(Float)

    quota_min: Mapped[Optional[int]] = mapped_column(Integer)
    quota_max: Mapped[Optional[int]] = mapped_column(Integer)
    dislivello: Mapped[Optional[int]] = mapped_column(Integer)
    esposizione: Mapped[Optional[str]] = mapped_column(String(20))   # es. "N,NE"
    difficolta: Mapped[Optional[str]] = mapped_column(String(20))    # scala della fonte
    tipo: Mapped[str] = mapped_column(String(20), default="scialpinismo")

    comune: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    istat: Mapped[Optional[str]] = mapped_column(String(10), index=True)
    valle: Mapped[Optional[str]] = mapped_column(String(60), index=True)
    paese: Mapped[str] = mapped_column(String(2), default="IT")
    eaws_region: Mapped[Optional[str]] = mapped_column(String(20), index=True)

    verificata: Mapped[bool] = mapped_column(Boolean, default=False)
    attiva: Mapped[bool] = mapped_column(Boolean, default=True)
    creata_il: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    uscite: Mapped[list["Uscita"]] = relationship(back_populates="gita")


class Utente(Base):
    __tablename__ = "utenti"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(64))
    nome: Mapped[Optional[str]] = mapped_column(String(120))

    comune_partenza: Mapped[Optional[str]] = mapped_column(String(100))
    istat_partenza: Mapped[Optional[str]] = mapped_column(String(10))
    lat_partenza: Mapped[Optional[float]] = mapped_column(Float)
    lon_partenza: Mapped[Optional[float]] = mapped_column(Float)

    ha_auto: Mapped[bool] = mapped_column(Boolean, default=False)
    posti_default: Mapped[int] = mapped_column(Integer, default=3)
    notifiche: Mapped[bool] = mapped_column(Boolean, default=True)
    creato_il: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class Uscita(Base):
    __tablename__ = "uscite"

    id: Mapped[int] = mapped_column(primary_key=True)
    autore_id: Mapped[int] = mapped_column(ForeignKey("utenti.id"), index=True)
    gita_id: Mapped[Optional[int]] = mapped_column(ForeignKey("gite.id"), index=True)
    # Per il tipo COMPAGNI la gita puo' essere assente: si indica solo una zona.
    zona: Mapped[Optional[str]] = mapped_column(String(60))

    tipo: Mapped[str] = mapped_column(String(12))  # OFFRO | CERCO | COMPAGNI
    data: Mapped[dt.date] = mapped_column(Date, index=True)
    flessibilita: Mapped[int] = mapped_column(Integer, default=0)  # +/- giorni
    ora_partenza: Mapped[Optional[str]] = mapped_column(String(5))  # "05:30"

    comune_partenza: Mapped[Optional[str]] = mapped_column(String(100))
    istat_partenza: Mapped[Optional[str]] = mapped_column(String(10))
    lat_partenza: Mapped[Optional[float]] = mapped_column(Float)
    lon_partenza: Mapped[Optional[float]] = mapped_column(Float)

    posti: Mapped[int] = mapped_column(Integer, default=0)  # offerti o richiesti
    note: Mapped[Optional[str]] = mapped_column(Text)
    stato: Mapped[str] = mapped_column(String(12), default="aperta")  # aperta|chiusa|annullata
    creata_il: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    gita: Mapped[Optional[Gita]] = relationship(back_populates="uscite")
    autore: Mapped[Utente] = relationship()


class Match(Base):
    __tablename__ = "match"
    __table_args__ = (UniqueConstraint("uscita_a_id", "uscita_b_id", name="uq_match"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    uscita_a_id: Mapped[int] = mapped_column(ForeignKey("uscite.id"), index=True)
    uscita_b_id: Mapped[int] = mapped_column(ForeignKey("uscite.id"), index=True)
    punteggio: Mapped[float] = mapped_column(Float, default=0)
    motivo: Mapped[Optional[str]] = mapped_column(String(300))
    notificato: Mapped[bool] = mapped_column(Boolean, default=False)
    creato_il: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class Percorso(Base):
    """Cache del percorso partenza -> attacco, con i comuni attraversati.
    Le coppie possibili sono poche centinaia: si calcolano una volta sola."""

    __tablename__ = "percorsi"
    __table_args__ = (UniqueConstraint("istat_partenza", "gita_id", name="uq_percorso"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    istat_partenza: Mapped[str] = mapped_column(String(10), index=True)
    gita_id: Mapped[int] = mapped_column(ForeignKey("gite.id"), index=True)
    km: Mapped[Optional[float]] = mapped_column(Float)
    minuti: Mapped[Optional[float]] = mapped_column(Float)
    comuni_istat: Mapped[list] = mapped_column(JSON, default=list)
    geometria: Mapped[Optional[dict]] = mapped_column(JSON)  # LineString GeoJSON
    calcolato_il: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class Comune(Base):
    __tablename__ = "comuni"

    istat: Mapped[str] = mapped_column(String(10), primary_key=True)
    nome: Mapped[str] = mapped_column(String(120), index=True)
    provincia: Mapped[Optional[str]] = mapped_column(String(60))
    regione: Mapped[Optional[str]] = mapped_column(String(60))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)


class Condizioni(Base):
    """Neve caduta e grado di pericolo ufficiale, per gita e per giorno.

    Sono due dati riportati, non elaborati: i centimetri li misura il modello
    meteo, il grado lo emette l'ente competente. Stanno in tabella perche' la
    vista Weekend possa leggerli in una query invece di rianalizzare le serie
    meteo di tutto il catalogo a ogni apertura. Li scrive aggiorna.py di notte.
    """

    __tablename__ = "condizioni"
    __table_args__ = (UniqueConstraint("gita_id", "giorno", name="uq_condizioni"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    gita_id: Mapped[int] = mapped_column(ForeignKey("gite.id"), index=True)
    giorno: Mapped[dt.date] = mapped_column(Date, index=True)

    neve_24h: Mapped[Optional[float]] = mapped_column(Float)
    neve_72h: Mapped[Optional[float]] = mapped_column(Float, index=True)
    ore_da_ultima_neve: Mapped[Optional[int]] = mapped_column(Integer)
    descrizione: Mapped[Optional[str]] = mapped_column(String(200))

    # grado ufficiale EAWS, riportato tale e quale. Nient'altro sul pericolo:
    # niente nostre elaborazioni, niente evidenziazioni di cosa "ti riguarda".
    grado_valanghe: Mapped[Optional[int]] = mapped_column(Integer)

    aggiornato_il: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class CacheMeteo(Base):
    __tablename__ = "cache_meteo"
    __table_args__ = (UniqueConstraint("gita_id", "giorno", name="uq_meteo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    gita_id: Mapped[int] = mapped_column(ForeignKey("gite.id"), index=True)
    giorno: Mapped[dt.date] = mapped_column(Date, index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    aggiornato_il: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class CacheBollettino(Base):
    __tablename__ = "cache_bollettini"
    __table_args__ = (UniqueConstraint("eaws_region", "giorno", name="uq_bollettino"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    eaws_region: Mapped[str] = mapped_column(String(20), index=True)
    giorno: Mapped[dt.date] = mapped_column(Date, index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    fonte_url: Mapped[Optional[str]] = mapped_column(String(400))
    aggiornato_il: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
