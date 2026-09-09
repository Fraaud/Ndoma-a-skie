"""Validazione dell'initData di una Telegram Mini App.

Telegram firma i dati dell'utente con HMAC-SHA256 usando come chiave
HMAC("WebAppData", bot_token). Senza questa verifica chiunque potrebbe
dichiararsi chiunque: e' l'unico punto di sicurezza dell'app, non saltarlo.
Doc: core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Utente

MAX_AGE_SECONDI = 24 * 3600


def verifica_init_data(init_data: str, bot_token: str, max_age: int = MAX_AGE_SECONDI) -> dict:
    if not init_data:
        raise ValueError("initData mancante")
    coppie = dict(parse_qsl(init_data, keep_blank_values=True))
    hash_ricevuto = coppie.pop("hash", None)
    if not hash_ricevuto:
        raise ValueError("hash mancante")

    data_check_string = "\n".join(f"{k}={coppie[k]}" for k in sorted(coppie))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    atteso = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(atteso, hash_ricevuto):
        raise ValueError("firma non valida")

    auth_date = int(coppie.get("auth_date", "0"))
    if max_age and time.time() - auth_date > max_age:
        raise ValueError("initData scaduto")

    utente = json.loads(coppie.get("user", "{}"))
    if not utente.get("id"):
        raise ValueError("utente assente")
    return utente


def utente_corrente(
    x_telegram_init_data: str = Header(default=""),
    db: Session = Depends(get_db),
) -> Utente:
    """Ricava (e crea al primo accesso) l'utente dall'initData."""
    if not settings.telegram_bot_token:
        raise HTTPException(500, "TELEGRAM_BOT_TOKEN non configurato")
    try:
        dati = verifica_init_data(x_telegram_init_data, settings.telegram_bot_token)
    except ValueError as e:
        raise HTTPException(401, f"Autenticazione Telegram fallita: {e}")

    u = db.query(Utente).filter_by(tg_id=dati["id"]).one_or_none()
    if u is None:
        u = Utente(
            tg_id=dati["id"],
            username=dati.get("username"),
            nome=" ".join(x for x in [dati.get("first_name"), dati.get("last_name")] if x) or None,
        )
        db.add(u)
        db.commit()
        db.refresh(u)
    else:
        cambiato = False
        if dati.get("username") and u.username != dati["username"]:
            u.username, cambiato = dati["username"], True
        if cambiato:
            db.commit()
    return u
