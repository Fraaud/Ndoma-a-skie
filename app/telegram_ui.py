"""Pezzi di interfaccia Telegram condivisi fra il web e il bot.

Il problema che risolvono: sapere CHI ha fatto match non serve a niente se poi
non c'e' un modo immediato di scrivergli. Su Telegram ci sono due strade, e
servono entrambe perche' molta gente non ha uno username:

  - con username -> link diretto  https://t.me/<username>
  - senza        -> menzione  tg://user?id=<id>, che apre il profilo ed e'
                    cliccabile perche' entrambi hanno gia' parlato col bot

Nessun numero di telefono, nessun contatto fuori da Telegram: si condivide
solo l'identita' che uno ha gia' scelto di mostrare.
"""
from __future__ import annotations

from typing import Any


def _esc(s: str | None) -> str:
    return (str(s or "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def menzione(utente: Any) -> str:
    """Nome cliccabile che apre la chat, con o senza username."""
    nome = _esc(utente.nome) or "qualcuno"
    if utente.username:
        return f'<a href="https://t.me/{_esc(utente.username)}">{nome}</a>'
    return f'<a href="tg://user?id={utente.tg_id}">{nome}</a>'


def link_chat(utente: Any) -> str:
    """Indirizzo che apre direttamente la chat con quella persona.

    Con username si usa il link t.me; senza, tg://user?id=, che il Bot API
    accetta come indirizzo di un bottone e che apre comunque la chat, salvo
    impostazioni di privacy restrittive dell'altra persona.
    """
    if utente.username:
        return f"https://t.me/{utente.username}"
    return f"tg://user?id={utente.tg_id}"


def bottoni_match(altro: Any) -> dict:
    """Un solo bottone: aprire la chat con l'altra persona.

    Niente bottone per l'app (il bot ce l'ha gia' fisso accanto al campo di
    testo) e niente passaggio intermedio: la notifica arriva a tutti e due,
    chi vuole scrivere apre la chat e scrive.

    Torna un dizionario perche' la notifica parte dal processo web, che parla
    con Telegram via HTTP.
    """
    nome = (str(altro.nome or "").split() or ["l'altra persona"])[0]
    return {"inline_keyboard": [[{
        "text": f"Scrivi a {nome}",
        "url": link_chat(altro),
    }]]}


def da_dizionario(markup: dict):
    """Converte la tastiera in oggetti python-telegram-bot, per il bot."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

    righe = []
    for riga in markup["inline_keyboard"]:
        bottoni = []
        for b in riga:
            b = dict(b)
            if "web_app" in b:
                b["web_app"] = WebAppInfo(url=b["web_app"]["url"])
            bottoni.append(InlineKeyboardButton(**b))
        righe.append(bottoni)
    return InlineKeyboardMarkup(righe)
