"""Bot Telegram: porta d'ingresso alla mini app, notifiche e promemoria.

Avvio (processo separato dal web):   python -m app.bot

Il bot fa poche cose e le fa bene: apre la mini app, risponde ai comandi
rapidi e manda il promemoria del giovedi'. Tutto il resto sta nella web app.
Il promemoria non e' un dettaglio: e' quello che tiene vivo il progetto.
Un bot che nessuno apre e' un bot morto, per quanto sia bella l'app dentro.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, Update, WebAppInfo
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from app import notifiche as notifiche_srv
from app.config import settings
from app.db import init_db, session_scope
from app.models import Gita, Uscita, Utente

logging.basicConfig(format="%(asctime)s  %(message)s", level=logging.INFO,
                    datefmt="%H:%M:%S")
# Le librerie parlano inglese e a raffica: httpx stampa una riga a ogni
# interrogazione di Telegram, cioe' ogni dieci secondi. Restano visibili solo
# i loro errori veri.
for rumorosa in ("httpx", "httpcore", "telegram.ext.Updater", "apscheduler"):
    logging.getLogger(rumorosa).setLevel(logging.WARNING)
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


async def _ciclo_recupero_notifiche(intervallo: int = 120) -> None:
    """Manda i match salvati ma mai notificati, per sempre.

    E' un semplice ciclo asyncio e NON la coda dei lavori della libreria:
    quella richiede l'estensione [job-queue], e se manca sparisce senza dire
    niente. Il recupero delle notifiche e' troppo importante per dipendere
    da una dipendenza opzionale.
    """
    from app.db import SessionLocal

    await asyncio.sleep(15)
    while True:
        db = SessionLocal()
        try:
            n = await notifiche_srv.notifica_arretrati(db)
            if n:
                log.info("recuperate %s notifiche di match arretrate", n)
        except Exception as e:
            log.warning("recupero notifiche fallito: %s", e)
        finally:
            db.close()
        await asyncio.sleep(intervallo)


async def aggiornamento_notturno(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Meteo, bollettini e punteggi, una volta al giorno.

    Serve dove non si puo' mettere un cron separato: su Railway il volume del
    database sta su un solo servizio, quindi l'aggiornamento deve girare qui.
    Su un server tradizionale si usa scripts/aggiorna.py da cron, e questo
    lavoro semplicemente rifa' un lavoro gia' fatto senza danno.
    """
    from app.aggiornamento import aggiorna_tutto
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        c = await aggiorna_tutto(db, verboso=False)
        log.info("aggiornamento notturno: %s gite, %s punteggi, %ss",
                 c["gite"], c["punteggi"], c["secondi"])
    except Exception as e:
        log.warning("aggiornamento notturno fallito: %s", e)
    finally:
        db.close()


async def _post_init(app: Application) -> None:
    # Il bottone permanente accanto al campo di testo: il modo piu' comodo per
    # riaprire l'app senza cercare il messaggio di /start. Se l'indirizzo non
    # e' https Telegram lo rifiuta: va segnalato, ma non deve far cadere il
    # bot, che per il resto (comandi, match, notifiche) funziona lo stesso.
    if not settings.webapp_url.startswith("https://"):
        log.warning("WEBAPP_URL non e' https (%s): la mini app non si aprira'. "
                    "Telegram accetta solo indirizzi https.", settings.webapp_url)
    try:
        await app.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Apri app",
                                         web_app=WebAppInfo(url=settings.webapp_url))
        )
    except Exception as e:
        log.warning("bottone della mini app non impostato: %s", e)
    app.create_task(_ciclo_recupero_notifiche())
    log.info("recupero notifiche attivo, ogni 2 minuti")


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
        if os.getenv("AGGIORNA_DAL_BOT", "").lower() in ("1", "true", "si"):
            app.job_queue.run_daily(aggiornamento_notturno, time=dt.time(4, 0))
            log.info("aggiornamento notturno attivo, ogni giorno alle 4:00")
    else:
        log.warning(
            "CODA DEI LAVORI ASSENTE: il promemoria del giovedi' non partira'. "
            "Installa le dipendenze aggiornate:  pip install -r requirements.txt"
        )
    log.info("bot in ascolto")
    app.run_polling()


if __name__ == "__main__":
    main()
