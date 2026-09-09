"""Esperienza dichiarata da chi usa l'app, e come si riassume in una riga.

Perche' esiste questo file
--------------------------
L'app nasce per far viaggiare meno macchine. Il rischio, pero', e' che
mettendo in contatto sconosciuti finisca per far nascere comitive in cui
nessuno ha mai fatto quel tipo di terreno: e in scialpinismo una comitiva
senza nessuno che sappia cosa fare non e' una gita meno bella, e' una gita
in cui un incidente diventa grave, perche' non c'e' chi soccorre.

Quello che facciamo NON e' filtrare. L'esperienza qui e' auto-dichiarata,
quindi non verifica niente e chiunque puo' scrivere quello che vuole; e chi
venisse escluso si organizzerebbe lo stesso nella chat del gruppo, solo con
meno informazioni di adesso. Quello che facciamo e' rendere visibile di cosa
e' fatto un gruppo PRIMA che si formi. Non dichiarare niente e' una risposta
anche quella, e infatti si vede scritto.

Le etichette stanno qui e non sparse nella pagina, cosi' se domani cambiano
si toccano in un posto solo - e i test possono controllarle.
"""
from __future__ import annotations

from typing import Optional

# Formazione: la domanda e' "hai fatto un corso", non "sei bravo".
FORMAZIONE = {
    "nessuna": "nessun corso",
    "corso": "corso di scialpinismo o valanghe",
    "guida": "guida alpina o istruttore",
}

# Ultima prova di ricerca ARTVA. E' una domanda migliore di "sai usarlo?",
# a cui rispondono di si' tutti: qui si dichiara un fatto, non un giudizio.
ARTVA_PROVA = {
    "mai": "mai fatta",
    "vecchia": "piu' di un anno fa",
    "stagione": "quest'inverno",
}

# Scala italiana di difficolta' sciistica.
DIFFICOLTA = {
    "MS": "MS - medio sciatore",
    "BS": "BS - buon sciatore",
    "OS": "OS - ottimo sciatore",
    "BSA": "BSA - buon sciatore alpinista",
    "OSA": "OSA - ottimo sciatore alpinista",
}

NON_DICHIARATA = "esperienza non dichiarata"


def _valida(valore: Optional[str], ammessi: dict) -> Optional[str]:
    v = (valore or "").strip()
    return v if v in ammessi else None


def pulisci(dati: dict) -> dict:
    """Normalizza quello che arriva dal modulo: fuori i valori inventati."""
    inverni = dati.get("inverni")
    try:
        inverni = int(inverni)
    except (TypeError, ValueError):
        inverni = None
    if inverni is not None and not (0 <= inverni <= 60):
        inverni = None

    artva = dati.get("artva")
    if artva not in (True, False):
        artva = None

    return {
        "inverni": inverni,
        "formazione": _valida(dati.get("formazione"), FORMAZIONE),
        "difficolta_abituale": _valida(dati.get("difficolta_abituale"), DIFFICOLTA),
        "artva": artva,
        # se non hai l'ARTVA la domanda sulla prova non ha senso
        "artva_prova": _valida(dati.get("artva_prova"), ARTVA_PROVA) if artva else None,
    }


def _inverni(n: Optional[int]) -> Optional[str]:
    if n is None:
        return None
    if n <= 0:
        return "prima stagione"
    if n == 1:
        return "1 inverno"
    return f"{n} inverni"


def riassunto(u) -> str:
    """Una riga sola, da mettere sotto il nome nelle schede.

    Compatta apposta: deve stare accanto a un nome senza far scorrere la
    pagina, altrimenti nessuno la legge.
    """
    pezzi = []

    inv = _inverni(getattr(u, "inverni", None))
    if inv:
        pezzi.append(inv)

    form = getattr(u, "formazione", None)
    if form == "guida":
        pezzi.append("guida o istruttore")
    elif form == "corso":
        pezzi.append("corso valanghe")
    elif form == "nessuna":
        pezzi.append("nessun corso")

    diff = getattr(u, "difficolta_abituale", None)
    if diff in DIFFICOLTA:
        pezzi.append(f"di solito fino a {diff}")

    artva = getattr(u, "artva", None)
    if artva is False:
        pezzi.append("senza ARTVA")
    elif artva is True:
        prova = ARTVA_PROVA.get(getattr(u, "artva_prova", None) or "")
        pezzi.append(f"ARTVA, prova {prova}" if prova else "ARTVA")

    return " · ".join(pezzi) if pezzi else NON_DICHIARATA


def dichiarata(u) -> bool:
    """Ha compilato almeno una delle risposte?"""
    return riassunto(u) != NON_DICHIARATA
