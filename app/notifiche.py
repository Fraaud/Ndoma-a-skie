"""Invio delle notifiche di match, con recupero di quelle non riuscite.

Perche' sta in un modulo suo: la notifica parte dal processo web subito dopo
la pubblicazione, ma se in quel momento qualcosa non va (server appena
riavviato, Telegram che non risponde, un errore nel codice) il match resta
salvato e nessuno lo viene a sapere. Il bot ricontrolla ogni due minuti gli
arretrati e li manda: la stessa funzione serve a entrambi i processi.
"""
from __future__ import annotations

import httpx
from sqlalchemy.orm import Session

from app import telegram_ui as tg_ui
from app.config import settings
from app.models import Gita, Match, Uscita, Utente

RUOLO = {"OFFRO": "offre posti", "CERCO": "cerca un passaggio",
         "COMPAGNI": "cerca compagnia"}


async def invia(chat_id: int, testo: str, tastiera: dict | None = None) -> bool:
    if not settings.telegram_bot_token:
        return False
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    corpo = {"chat_id": chat_id, "text": testo, "parse_mode": "HTML",
             "disable_web_page_preview": True}
    if tastiera:
        corpo["reply_markup"] = tastiera
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(url, json=corpo)
        if r.status_code != 200:
            print(f"notifica non inviata a {chat_id}: {r.text[:200]}")
            return False
        return True
    except Exception as e:
        print(f"notifica non inviata a {chat_id}: {e}")
        return False


def testo_match(db: Session, mia: Uscita, altra: Uscita, motivo: str | None) -> str:
    altro_autore = db.get(Utente, altra.autore_id)
    gita = db.get(Gita, altra.gita_id) if altra.gita_id else None
    dove = gita.nome if gita else (altra.zona or "zona da definire")
    return (
        f"<b>Match!</b>\n{tg_ui.menzione(altro_autore)} {RUOLO[altra.tipo]} per "
        f"<b>{dove}</b> il {altra.data.strftime('%d/%m')}"
        + (f" da {altra.comune_partenza}" if altra.comune_partenza else "")
        + (f", partenza {altra.ora_partenza}" if altra.ora_partenza else "")
        + (f"\n<i>{motivo}</i>" if motivo else "")
        + "\n\nScrivetevi per accordarvi: l'app non gestisce la prenotazione."
    )


async def notifica_match(db: Session, m: Match) -> bool:
    """Avvisa entrambe le persone. Segna il match come notificato solo se
    almeno un messaggio e' partito, cosi' i falliti vengono ritentati."""
    a, b = db.get(Uscita, m.uscita_a_id), db.get(Uscita, m.uscita_b_id)
    if not a or not b:
        return False

    inviati = 0
    for mia, altra in ((a, b), (b, a)):
        autore = db.get(Utente, mia.autore_id)
        altro_autore = db.get(Utente, altra.autore_id)
        if not autore or not autore.notifiche or not altro_autore:
            continue
        ok = await invia(
            autore.tg_id,
            testo_match(db, mia, altra, m.motivo),
            tg_ui.bottoni_match(altro_autore),
        )
        inviati += int(ok)

    if inviati:
        m.notificato = True
        db.commit()
    return bool(inviati)


async def notifica_arretrati(db: Session, limite: int = 20) -> int:
    """Match salvati ma mai notificati. Lo chiama il bot ogni due minuti."""
    pendenti = (
        db.query(Match)
        .filter(Match.notificato.is_(False))
        .order_by(Match.id.desc())
        .limit(limite)
        .all()
    )
    fatti = 0
    for m in pendenti:
        try:
            fatti += int(await notifica_match(db, m))
        except Exception as e:
            print(f"match {m.id} non notificato: {e}")
    return fatti
