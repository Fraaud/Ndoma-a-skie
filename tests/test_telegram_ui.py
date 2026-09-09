"""Test dei pezzi di interfaccia Telegram.

Il punto delicato: chi non ha uno username deve restare contattabile, e i
nomi propri non devono poter rompere l'HTML del messaggio.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import telegram_ui as tg  # noqa: E402


class UtenteFinto:
    def __init__(self, tg_id, username=None, nome=None):
        self.tg_id, self.username, self.nome = tg_id, username, nome


def test_menzione_con_username():
    m = tg.menzione(UtenteFinto(1, "marco_cn", "Marco"))
    assert 'href="https://t.me/marco_cn"' in m and ">Marco<" in m


def test_menzione_senza_username_resta_cliccabile():
    """Meta' della gente non ha uno username: senza questo ramo il match
    arriverebbe senza alcun modo di rispondere."""
    m = tg.menzione(UtenteFinto(4242, None, "Giulia"))
    assert 'href="tg://user?id=4242"' in m and ">Giulia<" in m


def test_menzione_senza_nome():
    assert "qualcuno" in tg.menzione(UtenteFinto(7))


def test_nome_pericoloso_non_rompe_html():
    m = tg.menzione(UtenteFinto(9, None, 'Gian<b>"&'))
    assert "<b>" not in m.replace('<a href="tg://user?id=9">', "")
    assert "&lt;b&gt;" in m and "&amp;" in m


def test_bottone_apre_la_chat_con_username():
    k = tg.bottoni_match(UtenteFinto(1, "marco_cn", "Marco Rossi"))
    righe = k["inline_keyboard"]
    assert len(righe) == 1 and len(righe[0]) == 1        # un solo bottone
    assert righe[0][0]["url"] == "https://t.me/marco_cn"
    assert righe[0][0]["text"] == "Scrivi a Marco"       # solo il nome proprio


def test_bottone_apre_la_chat_anche_senza_username():
    """Senza username il bottone deve comunque aprire la chat: e' il caso di
    meta' degli utenti Telegram."""
    k = tg.bottoni_match(UtenteFinto(4242, None, "Giulia"))
    b = k["inline_keyboard"][0][0]
    assert b["url"] == "tg://user?id=4242"
    assert b["text"] == "Scrivi a Giulia"


def test_nessun_bottone_inutile():
    """Niente 'Apri l'app' (il bot ce l'ha gia' fisso) e niente passaggi
    intermedi: un bottone solo, che fa la cosa che serve."""
    k = tg.bottoni_match(UtenteFinto(1, "x", "X"))
    tutti = [b for riga in k["inline_keyboard"] for b in riga]
    assert len(tutti) == 1
    assert "web_app" not in tutti[0] and "callback_data" not in tutti[0]


def test_utente_senza_nome():
    b = tg.bottoni_match(UtenteFinto(9, "pippo", None))["inline_keyboard"][0][0]
    assert b["text"] == "Scrivi a l'altra persona"
