"""Il ciclo di vita di un passaggio: posti liberi, chiusura, scadenza.

Perche' NON c'e' una prenotazione
---------------------------------
La strada ovvia sarebbe: chi cerca chiede il posto, chi guida accetta, i
posti scalano. E' esatta, e qui sarebbe sbagliata: **la gente si accorda in
chat comunque**, e poi non torna a premere il bottone. Lo stato dell'app
andrebbe alla deriva rispetto alla realta', e un "2 posti liberi" falso e'
peggio di nessun numero, perche' qualcuno ci conta sopra.

Quindi il conto lo tiene **chi guida**, da un lato solo e con un tocco:
"ho preso qualcuno", "sono pieno". E' come funziona davvero.

Le tre cose che l'app fa da se'
-------------------------------
1. **A zero posti liberi l'uscita si chiude**, e chi aveva un match con lei
   viene avvisato: "l'auto e' piena". Senza questo il quarto e il quinto
   scrivono per un posto che non c'e' piu'.
2. **Chi cerca ha un "sistemato"**, che chiude la sua richiesta e avvisa gli
   autisti che gli avevano scritto. Senza questo tre autisti insistono con
   uno che ha gia' risolto.
3. **Le uscite passate si chiudono da sole.** Prima restavano "aperta" per
   sempre: non si vedevano nell'elenco (che parte da oggi) ma nel profilo di
   chi le aveva pubblicate si', e in archivio erano fantasmi.

Niente di tutto questo prenota niente: sono tre modi di non far perdere
tempo alle persone.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

# Perche' un'uscita e' chiusa. Le parole non sono intercambiabili: a chi
# aveva un match si dice una cosa diversa in ognuno dei casi.
CHIUSURE = {
    "pieno": {
        "etichetta": "auto piena",
        "avviso": "{chi} ha completato l'auto per {dove} il {quando}.",
    },
    "sistemato": {
        "etichetta": "ha trovato un passaggio",
        "avviso": "{chi} ha trovato un passaggio per {dove} il {quando}: "
                  "non sta piu' cercando.",
    },
    "annullata": {
        "etichetta": "annullata",
        "avviso": "{chi} ha annullato l'uscita per {dove} il {quando}.",
    },
    "scaduta": {
        "etichetta": "passata",
        "avviso": "",       # a cose fatte non si avvisa nessuno
    },
}

# Chi puo' chiudere e con che motivo: un passeggero non "completa l'auto" e
# un autista non "trova un passaggio".
MOTIVI_PER_TIPO = {
    "OFFRO": ("pieno", "annullata"),
    "CERCO": ("sistemato", "annullata"),
}


def presi(us) -> int:
    """Quanti posti sono gia' andati. None vale 0: la colonna e' stata
    aggiunta a un database che esisteva gia'."""
    return max(0, int(getattr(us, "presi", None) or 0))


def liberi(us) -> int:
    """I posti ancora disponibili su un'offerta.

    Su una richiesta (CERCO) non vuol dire niente: chi cerca dichiara di
    quanti posti ha bisogno, non quanti ne offre.
    """
    if us.tipo != "OFFRO":
        return 0
    return max(0, int(us.posti or 0) - presi(us))


def pieno(us) -> bool:
    return us.tipo == "OFFRO" and int(us.posti or 0) > 0 and liberi(us) == 0


def in_parole(us) -> str:
    """Lo stato dei posti, come si legge nell'elenco."""
    if us.tipo != "OFFRO":
        n = int(us.posti or 0)
        return "cerca un posto" if n <= 1 else f"cerca {n} posti"
    totali = int(us.posti or 0)
    if totali <= 0:
        return "nessun posto libero"
    l = liberi(us)
    if l == 0:
        return "auto piena"
    if l == totali:
        return f"{totali} posti liberi" if totali != 1 else "1 posto libero"
    return f"{l} di {totali} liberi"


def imposta_presi(us, quanti: int) -> int:
    """Aggiorna i posti occupati, dentro i limiti. Restituisce i liberi.

    Si passa il numero assoluto e non un +1: due tocchi rapidi sullo stesso
    pulsante, o un tocco ripetuto perche' la rete e' lenta, con un delta
    conterebbero due volte.
    """
    if us.tipo != "OFFRO":
        raise ValueError("i posti li tiene solo chi offre un passaggio")
    us.presi = max(0, min(int(us.posti or 0), int(quanti)))
    return liberi(us)


def chiudi(us, motivo: str, quando: dt.datetime | None = None) -> None:
    if motivo not in CHIUSURE:
        raise ValueError(f"motivo di chiusura sconosciuto: {motivo}")
    us.stato = "chiusa"
    us.chiusa_perche = motivo
    us.chiusa_il = quando or dt.datetime.now(dt.timezone.utc)


def motivo_ammesso(us, motivo: str) -> bool:
    return motivo in MOTIVI_PER_TIPO.get(us.tipo, ())


def testo_chiusura(us, autore, dove: str) -> str:
    """Il messaggio per chi aveva un match con quest'uscita."""
    schema = CHIUSURE.get(us.chiusa_perche or "", {}).get("avviso", "")
    if not schema:
        return ""
    return schema.format(
        chi=(autore.nome if autore and autore.nome else "Qualcuno"),
        dove=dove,
        quando=us.data.strftime("%d/%m"),
    )


def etichetta_chiusura(us) -> Optional[str]:
    if us.stato != "chiusa":
        return None
    return CHIUSURE.get(us.chiusa_perche or "", {}).get("etichetta", "chiusa")


# --------------------------------------------------------------- scadenza


def scadute(db, oggi: dt.date | None = None) -> list:
    """Le uscite aperte con la data passata.

    Non si cancellano: restano nel profilo di chi le ha pubblicate, e chiuse
    dicono la verita' - "passata" - invece di sembrare ancora in cerca di
    qualcuno.
    """
    from app.models import Uscita

    oggi = oggi or dt.date.today()
    return (db.query(Uscita)
            .filter(Uscita.stato == "aperta", Uscita.data < oggi)
            .all())


def chiudi_scadute(db, oggi: dt.date | None = None) -> int:
    n = 0
    for us in scadute(db, oggi):
        chiudi(us, "scaduta")
        n += 1
    if n:
        db.commit()
    return n


# ------------------------------------------- chi va avvisato di una chiusura


def controparti(db, us) -> list:
    """Le persone che avevano un match con quest'uscita.

    Sono quelle a cui la chiusura cambia qualcosa: gli si dice una volta e
    basta, cosi' non scrivono a un posto che non c'e' piu'.
    """
    from app.models import Match, Uscita

    righe = (db.query(Match)
             .filter((Match.uscita_a_id == us.id) | (Match.uscita_b_id == us.id))
             .all())
    altri_id = [m.uscita_b_id if m.uscita_a_id == us.id else m.uscita_a_id
                for m in righe]
    if not altri_id:
        return []
    return (db.query(Uscita)
            .filter(Uscita.id.in_(altri_id), Uscita.stato == "aperta")
            .all())
