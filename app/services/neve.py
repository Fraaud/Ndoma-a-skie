"""Quanta neve e' caduta nelle ultime 72 ore. Solo questo.

Qui non si calcola nessun punteggio di qualita' della neve e nessun indice
nostro: si riporta una quantita' misurata dal modello meteo, come si
riporterebbe una temperatura.

Il motivo e' che un punteggio inventato da noi finisce per essere letto come
un giudizio, e ordinare le gite per "quanto sara' bella" spinge verso le
giornate con piu' neve fresca, che sono anche quelle in cui il pericolo di
valanghe e' piu' alto. Il fatto si riporta; il giudizio lo fa il bollettino,
e la decisione chi va in montagna.

Quando c'e' neve fresca, l'avvertenza qui sotto accompagna SEMPRE il dato.
Non e' una valutazione dell'itinerario - non sappiamo dirla e non proviamo -
ma il richiamo generale che sta in apertura di qualunque manuale.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from app.services import meteo as meteo_srv

AVVERTENZA_NEVE_FRESCA = (
    "Ha nevicato da poco. I giorni successivi a una nevicata sono quelli in cui "
    "il pericolo di valanghe e' piu' alto: la neve nuova non si e' ancora "
    "assestata e il vento puo' averla accumulata in lastroni. "
    "Leggi il bollettino integrale prima di decidere."
)


def _somma(serie: list | None) -> float:
    return float(sum(v for v in (serie or []) if v is not None))


def nevicato(dati_meteo: dict, giorno: dt.date, ora: int = 8) -> dict[str, Any]:
    """Neve caduta prima della mattina di `giorno`. Nessun punteggio."""
    riferimento = dt.datetime.combine(giorno, dt.time(ora, 0))
    f72 = meteo_srv.finestra(dati_meteo, riferimento, 72)
    if not f72:
        return {"disponibile": False, "motivo": "dati meteo non disponibili"}

    neve72 = _somma(f72.get("snowfall"))
    neve48 = _somma(meteo_srv.finestra(dati_meteo, riferimento, 48).get("snowfall"))
    neve24 = _somma(meteo_srv.finestra(dati_meteo, riferimento, 24).get("snowfall"))

    # ore dall'ultima nevicata significativa (>= 0.5 cm in un'ora)
    ore_da_neve = None
    serie = f72.get("snowfall") or []
    for i in range(len(serie) - 1, -1, -1):
        if (serie[i] or 0) >= 0.5:
            ore_da_neve = len(serie) - 1 - i
            break

    ha_nevicato = neve72 >= 1.0
    if not ha_nevicato:
        descrizione = "nessuna nevicata nelle ultime 72 ore"
    else:
        pezzi = [f"{neve72:.0f} cm nelle ultime 72 ore"]
        if neve24 >= 1:
            pezzi.append(f"{neve24:.0f} nelle ultime 24")
        if ore_da_neve is not None:
            pezzi.append(f"ultima nevicata {ore_da_neve}h fa")
        descrizione = ", ".join(pezzi)

    return {
        "disponibile": True,
        "ha_nevicato": ha_nevicato,
        "neve_24h_cm": round(neve24, 1),
        "neve_48h_cm": round(neve48, 1),
        "neve_72h_cm": round(neve72, 1),
        "ore_da_ultima_neve": ore_da_neve,
        "descrizione": descrizione,
        "avvertenza": AVVERTENZA_NEVE_FRESCA if ha_nevicato else None,
    }
