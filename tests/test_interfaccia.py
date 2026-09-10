"""Controlli sui file statici.

Sono verifiche grezze - si leggono i file e si cercano delle stringhe - ma
prendono proprio gli errori che sfuggono guardando l'app: una voce di menu
rimasta orfana, un elenco di etichette copiato nel JavaScript che il giorno
dopo non corrisponde piu' a quello del server.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import segnalazioni as sg  # noqa: E402
from app import tracce as sg_tracce  # noqa: E402

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "app", "static")


def _leggi(nome: str) -> str:
    with open(os.path.join(STATIC, nome), encoding="utf-8") as f:
        return f.read()


def test_il_menu_ha_quattro_voci():
    """Quattro, non cinque: Sapere e' entrato nel profilo.

    Il menu e' l'unica cosa che si vede da ogni schermata: ogni voce in piu'
    e' spazio tolto alle altre, e Sapere e' roba che si legge una volta.
    """
    html = _leggi("index.html")
    voci = html.count('data-vista="')
    assert voci == 4, f"la barra ha {voci} voci"
    assert 'data-vista="sapere"' not in html


def test_da_sapere_si_torna_indietro():
    """Una schermata senza voce nel menu deve avere un modo di uscire,
    altrimenti si resta intrappolati."""
    js = _leggi("app.js")
    i = js.index("VISTE.sapere")
    assert "vai('profilo')" in js[i:i + 900]


def test_al_profilo_si_arriva_a_sapere():
    js = _leggi("app.js")
    i = js.index("VISTE.profilo")
    assert "vai('sapere')" in js[i:], "dal profilo non si raggiunge piu' Sapere"


def test_le_etichette_delle_condizioni_arrivano_dal_server():
    """Il vocabolario sta in app/segnalazioni.py, in un posto solo.

    Copiarlo nel JavaScript vorrebbe dire averne due elenchi, e fra sei mesi
    uno dei due sbagliato - con l'utente che tocca un'etichetta e il server
    che ne salva un'altra. Qui si controlla che le pillole si costruiscano
    da quello che manda il server, e che nel JavaScript non sia comparso un
    elenco di chiavi scritto a mano.
    """
    js = _leggi("app.js")
    for gruppo in ("neve", "traccia", "accesso"):
        assert f'pillole("{gruppo}", voc.{gruppo})' in js, \
            f"le pillole di «{gruppo}» non vengono dal vocabolario del server"
    # come sarebbe scritta una chiave dentro un oggetto JavaScript. La forma
    # senza virgolette non si controlla: "Rompi il ghiaccio:" e' una frase.
    for chiave in list(sg.NEVE) + list(sg.TRACCIA) + list(sg.ACCESSO):
        for forma in (f'"{chiave}":', f"'{chiave}':"):
            assert forma not in js, \
                f"«{chiave}» e' in un elenco scritto a mano nel JavaScript"


def test_le_pillole_si_toccano_col_guanto():
    """40px di lato: si usano dopo una gita, in macchina, col guanto."""
    css = _leggi("style.css")
    i = css.index(".pillole .pillola")
    assert "min-height:40px" in css[i:i + 300]


def test_le_righe_di_un_elenco_sono_alte_almeno_44px():
    css = _leggi("style.css")
    i = css.index(".voce{")
    assert "min-height:44px" in css[i:i + 260]


def test_nel_tema_scuro_si_scambiano_anche_i_colori_del_testo():
    """Il bug che ha reso necessario questo test: nel tema scuro avevo
    scambiato le due superfici (schede piu' chiare della pagina, come su
    iOS) ma non i colori di ripiego del testo. Dentro Telegram non si
    vedeva - vincono le variabili del tema - ma chi apriva l'app dal
    browser col telefono in scuro trovava schede scure e testo nero.
    """
    css = _leggi("style.css")
    i = css.index("@media (prefers-color-scheme: dark)")
    blocco = css[i:css.index("}", css.index("}", i) + 1)]
    for variabile in ("--fondo", "--scheda", "--testo", "--secondario"):
        assert variabile in blocco, \
            f"{variabile} non viene ridefinita nel tema scuro"


def test_i_colori_ufficiali_eaws_sono_intatti():
    """Sono lo standard europeo del pericolo valanghe, non una nostra scelta
    estetica: nessun ristudio dell'interfaccia li puo' armonizzare. Il grado
    5 ha il bordo nero perche' lo prevede lo standard."""
    css = _leggi("style.css").replace(" ", "")
    for regola in (".g1{background:#ccff66}", ".g2{background:#ffff00}",
                   ".g3{background:#ff9900}", ".g4{background:#ff0000}"):
        assert regola in css, f"colore EAWS cambiato: {regola}"
    i = css.index(".g5{")
    assert "background:#ff0000" in css[i:i + 80]
    assert "border:3pxsolid#000" in css[i:i + 80]


# ------------------------------------------------------------- emergenza


def _blocco(js: str, inizio: str, fine: str) -> str:
    i = js.index(inizio)
    return js[i:js.index(fine, i)]


def test_emergenza_non_chiede_niente_al_server():
    """E' il punto di tutta la schermata: in valle il campo non c'e', ed e'
    esattamente il momento in cui serve. La posizione la da' il GPS, i
    ripari sono gia' nel telefono."""
    js = _leggi("app.js")
    corpo = _blocco(js, "VISTE.emergenza", "window.apriFuori")
    assert "api(" not in corpo, "Emergenza fa una chiamata al server"


def test_la_posizione_non_va_al_nostro_server():
    """Non esiste un endpoint a cui mandarla, e non deve esistere: il riparo
    piu' vicino lo calcola il telefono."""
    js = _leggi("app.js")
    for sospetto in ("/emergenza", "/posizione", "lat=' + POSIZIONE",
                     "POSIZIONE.lat + '&"):
        assert sospetto not in js.replace('"', "'"), \
            f"la posizione sembra finire in una richiesta: {sospetto}"


def test_i_ripari_si_scaricano_prima_e_si_tengono():
    js = _leggi("app.js")
    assert "ricordaPerEmergenza" in _blocco(js, "async function disegnaPosti", "\n}\n")
    # e la lettura del deposito e' sempre protetta: in una finestra privata
    # localStorage esiste ma lancia
    i = js.index("function leggiEmergenza")
    assert "catch" in js[i:i + 400]


def test_dal_profilo_si_arriva_allemergenza():
    js = _leggi("app.js")
    assert "vai('emergenza')" in js[js.index("VISTE.profilo"):]


def test_il_gps_si_spegne_quando_si_esce():
    """Batteria: in montagna e' quella che serve per chiamare."""
    js = _leggi("app.js")
    i = js.index("function vai(nome, arg)")
    assert "clearWatch" in js[i:i + 900], \
        "uscendo da Emergenza il GPS resta in ascolto"


# ----------------------------------------------------------------- traccia


def test_una_linea_calcolata_si_vede_che_e_calcolata():
    """Una linea su una mappa e' un invito a seguirla: se non l'ha
    percorsa nessuno, deve essere scritto sopra."""
    js = _leggi("app.js")
    corpo = _blocco(js, "async function disegnaTraccia", "function modulodiCaricamento")
    assert "adatta_a_sci" in corpo, "il percorso calcolato non viene distinto"
    assert "origine_etichetta" in corpo, "la provenienza non si mostra"


def test_le_parole_della_provenienza_arrivano_dal_server():
    """Come per le condizioni: il vocabolario sta in un posto solo."""
    js = _leggi("app.js")
    for etichetta in (sg_tracce.ORIGINI[o]["etichetta"] for o in sg_tracce.ORIGINI):
        assert etichetta not in js, \
            f"«{etichetta}» e' scritta a mano nel JavaScript"


def test_il_caricamento_dice_che_deve_essere_una_registrazione_tua():
    """E' la frase che regge tutto: il server non puo' verificarlo."""
    js = _leggi("app.js")
    corpo = _blocco(js, "function modulodiCaricamento", "function collegaCaricamento")
    testo = corpo.lower()
    assert "fatta da te" in testo
    assert "altri siti" in testo


# ------------------------------------------------- parcheggi, ripari, piole


def test_gli_orari_di_apertura_non_si_mostrano_da_nessuna_parte():
    """OSM li ha, ma nelle valli sono vecchi di anni."""
    js = _leggi("app.js")
    assert "opening_hours" not in js


def test_la_capienza_del_parcheggio_e_in_evidenza():
    """E' il dato per cui questa app esiste: sei macchine in un piazzale."""
    js = _leggi("app.js")
    corpo = _blocco(js, "async function disegnaPosti", "VISTE.emergenza")
    assert "capienza" in corpo
    assert "posti-num" in corpo
