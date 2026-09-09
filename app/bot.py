"""Bot Telegram: porta d'ingresso alla mini app, notifiche e promemoria.

Avvio (processo separato dal web):   python -m app.bot

Il bot fa poche cose e le fa bene: apre la mini app, risponde ai comandi
rapidi e manda il promemoria del giovedi'. Tutto il resto sta nella web app.
Il promemoria non e' un dettaglio: e' quello che tiene vivo il progetto.
Un bot che nessuno apre e' un bot morto, per quanto sia bella l'app dentro.
"""
from __future__ import annotations

import datetime as dt
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, Update, WebAppInfo
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from app.config import settings
from app.db import init_db, session_scope
from app.models import Gita, Uscita, Utente

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("ndoma")


def _tastiera() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Apri Ndoma a skié", web_app=WebAppInfo(url=settings.webapp_url))
    ]])


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    u = update.effective_user
    with session_scope() as db:
        if not db.query(Utente).filter_by(tg_id=u.id).one_or_none():
            db.add(Utente(tg_id=u.id, username=u.username,
                          nome=" ".join(x for x in [u.first_name, u.last_name] if x)))
    await update.message.reply_text(
        "<b>NDOMA A SKIÉ</b>\n\n"
        "Passaggi in auto per andare in gita, e per ogni itinerario meteo, "
        "qualita' della neve e bollettino valanghe.\n\n"
        "Apri l'app qui sotto: pubblichi un'offerta o una ricerca in due tap, "
        "e ti avviso appena qualcuno combacia.",
        parse_mode=ParseMode.HTML,
        reply_markup=_tastiera(),
    )


async def weekend(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    with session_scope() as db:
        n = db.query(Gita).count()
    await update.message.reply_text(
        f"Catalogo: {n} itinerari.\nApri l'app per vedere le condizioni previste "
        "e chi va dove questo weekend.",
        reply_markup=_tastiera(),
    )


async def mie(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    with session_scope() as db:
        u = db.query(Utente).filter_by(tg_id=update.effective_user.id).one_or_none()
        if not u:
            await update.message.reply_text("Non ti conosco ancora: /start")
            return
        uscite = (
            db.query(Uscita)
            .filter(Uscita.autore_id == u.id, Uscita.stato == "aperta",
                    Uscita.data >= dt.date.today())
            .order_by(Uscita.data)
            .all()
        )
        if not uscite:
            await update.message.reply_text("Non hai uscite aperte.", reply_markup=_tastiera())
            return
        righe = []
        for x in uscite:
            g = db.get(Gita, x.gita_id) if x.gita_id else None
            righe.append(f"- {x.data.strftime('%d/%m')} {x.tipo.lower()} "
                         f"{g.nome if g else (x.zona or '')}")
    await update.message.reply_text("Le tue uscite:\n" + "\n".join(righe),
                                    reply_markup=_tastiera())


async def promemoria_settimanale(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Giovedi' sera: 'cosa fate questo weekend?'.

    Va nel gruppo se configurato, altrimenti ai singoli che hanno le notifiche
    attive. Senza questo messaggio la gente si dimentica che il bot esiste.
    """
    with session_scope() as db:
        aperte = (
            db.query(Uscita)
            .filter(Uscita.stato == "aperta", Uscita.data >= dt.date.today(),
                    Uscita.data <= dt.date.today() + dt.timedelta(days=4))
            .order_by(Uscita.data)
            .all()
        )
        righe = []
        for x in aperte[:15]:
            g = db.get(Gita, x.gita_id) if x.gita_id else None
            simbolo = {"OFFRO": "auto", "CERCO": "cerca passaggio", "COMPAGNI": "cerca compagnia"}[x.tipo]
            righe.append(f"- {x.data.strftime('%a %d/%m')} - {g.nome if g else x.zona} "
                         f"({simbolo}, da {x.comune_partenza or '?'})")
        destinatari = [u.tg_id for u in db.query(Utente).filter(Utente.notifiche.is_(True)).all()]

    testo = "<b>Weekend in arrivo</b>\n\n"
    testo += ("Per ora c'e' questo:\n" + "\n".join(righe)) if righe else \
             "Ancora nessuno ha detto dove va. Rompi il ghiaccio tu."
    testo += "\n\nApri l'app per vedere neve e valanghe e per aggiungerti."

    if settings.telegram_group_id:
        await ctx.bot.send_message(settings.telegram_group_id, testo,
                                   parse_mode=ParseMode.HTML, reply_markup=_tastiera())
    else:
        for tg_id in destinatari:
            try:
                await ctx.bot.send_message(tg_id, testo, parse_mode=ParseMode.HTML,
                                           reply_markup=_tastiera())
            except Exception as e:
                log.warning("promemoria non inviato a %s: %s", tg_id, e)


async def _post_init(app: Application) -> None:
    # il bottone permanente accanto al campo di testo: e' il modo piu' comodo
    # per riaprire l'app senza cercare il messaggio di /start
    await app.bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(text="Apri app", web_app=WebAppInfo(url=settings.webapp_url))
    )


def main() -> None:
    if not settings.telegram_bot_token:
        raise SystemExit("Manca TELEGRAM_BOT_TOKEN nel .env")
    init_db()
    app = Application.builder().token(settings.telegram_bot_token).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("weekend", weekend))
    app.add_handler(CommandHandler("mie", mie))

    if app.job_queue:
        # giovedi' alle 19:00 (ora del server)
        app.job_queue.run_daily(promemoria_settimanale, time=dt.time(19, 0), days=(3,))
    log.info("bot avviato")
    app.run_polling()


if __name__ == "__main__":
    main()
