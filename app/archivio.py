"""Dove sta il database, e se sopravvivera' al prossimo deploy.

Perche' serve una funzione per questo
-------------------------------------
Su una piattaforma come Railway il codice viene ricostruito a ogni push:
tutto quello che sta dentro l'immagine sparisce. Sopravvive solo la cartella
del volume. Se il file SQLite finisce per sbaglio nell'immagine - basta un
DATABASE_URL con un percorso relativo - l'app riparte perfettamente ma
vuota: catalogo da reimportare e, soprattutto, iscritti e loro preferenze
da rifare. E non c'e' nessun errore da nessuna parte, perche' dal punto di
vista del programma non e' successo niente di sbagliato.

Per accorgersene senza aspettare le lamentele, l'unico segnale affidabile e'
il filesystem: un volume montato e' un dispositivo DIVERSO da quello su cui
sta il codice. Se sono lo stesso, il database e' dentro l'immagine.
"""
from __future__ import annotations

import datetime as dt
import os

from app.config import BASE_DIR, DATA_DIR, settings


def percorso_sqlite() -> str | None:
    """Il file dietro settings.database_url, se e' SQLite."""
    url = settings.database_url
    if not url.startswith("sqlite"):
        return None
    p = url.split("sqlite:///", 1)[-1]
    if p.startswith("/"):          # era sqlite://// (percorso assoluto)
        return p
    return os.path.abspath(os.path.join(BASE_DIR, p))


def stato() -> dict:
    """Riassunto controllabile da fuori, via /api/salute."""
    p = percorso_sqlite()
    if p is None:
        # un database vero (Postgres) e' persistente per definizione
        return {"tipo": "server", "persistente": True, "percorso": None}

    esiste = os.path.exists(p)
    d = {
        "tipo": "sqlite",
        "percorso": p,
        "esiste": esiste,
        "byte": os.path.getsize(p) if esiste else 0,
        "modificato": (dt.datetime.fromtimestamp(os.path.getmtime(p)).isoformat(
            timespec="seconds") if esiste else None),
        "cartella_dati": DATA_DIR,
        "persistente": su_volume(os.path.dirname(p) or DATA_DIR),
    }
    if not d["persistente"]:
        d["avviso"] = (
            "il database sta dentro l'immagine, non su un volume: al prossimo "
            "deploy si perdono iscritti e catalogo. Monta un volume e imposta "
            "DATA_DIR sul suo punto di mount."
        )
    return d


def su_volume(cartella: str) -> bool:
    """La cartella sta su un dispositivo diverso da quello del codice?

    E' l'unico modo di distinguere un volume montato da una cartella
    qualunque dentro il container. In sviluppo locale, dove non c'e' nessun
    volume, non e' un problema da segnalare: i file stanno sul disco di casa
    e nessuno li cancella.
    """
    if not os.getenv("DATA_DIR"):
        return True  # sviluppo locale: nessun deploy che cancella niente
    try:
        return os.stat(cartella).st_dev != os.stat(BASE_DIR).st_dev
    except OSError:
        return False


def riga_di_avvio() -> str:
    """Una riga da stampare all'avvio, cosi' si vede nei log del deploy."""
    s = stato()
    if s["tipo"] == "server":
        return "archivio: database su server (persistente)"
    dove = "sul volume" if s["persistente"] else "DENTRO L'IMMAGINE (si perde!)"
    quanto = f"{s['byte'] / 1_048_576:.1f} MB" if s["esiste"] else "ancora vuoto"
    return f"archivio: {s['percorso']} - {dove}, {quanto}"
