"""Powder score: stima della QUALITA' della neve, non della sicurezza.

Attenzione, e' il punto piu' delicato del progetto: neve fresca abbondante
piu' vento e' insieme la giornata piu' bella e la ricetta del lastrone.
Per questo la funzione restituisce sempre, accanto al punteggio, un campo
`avviso_valanghe` quando ricorrono quelle condizioni. Non nascondere mai
quell'avviso nell'interfaccia: chi vede 5 fiocchi deve vedere anche quello.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from app.services import meteo as meteo_srv


def _somma(serie: list | None) -> float:
    return float(sum(v for v in (serie or []) if v is not None))


def _max(serie: list | None) -> float:
    valori = [v for v in (serie or []) if v is not None]
    return float(max(valori)) if valori else 0.0


def _media(serie: list | None) -> float | None:
    valori = [v for v in (serie or []) if v is not None]
    return sum(valori) / len(valori) if valori else None


def calcola(dati_meteo: dict, giorno: dt.date, ora: int = 8) -> dict[str, Any]:
    """Punteggio 0-5 per la mattina di `giorno`."""
    riferimento = dt.datetime.combine(giorno, dt.time(ora, 0))
    f72 = meteo_srv.finestra(dati_meteo, riferimento, 72)
    f24 = meteo_srv.finestra(dati_meteo, riferimento, 24)
    if not f72:
        return {"punteggio": None, "motivo": "dati meteo non disponibili"}

    neve72 = _somma(f72.get("snowfall"))
    neve24 = _somma(f24.get("snowfall"))
    neve48 = _somma(meteo_srv.finestra(dati_meteo, riferimento, 48).get("snowfall"))

    # --- ore dall'ultima nevicata significativa (>= 0.5 cm/h)
    ore_da_neve = None
    serie_neve = f72.get("snowfall") or []
    for i in range(len(serie_neve) - 1, -1, -1):
        if (serie_neve[i] or 0) >= 0.5:
            ore_da_neve = len(serie_neve) - 1 - i
            break

    # --- vento: quello che conta e' durante e dopo la nevicata
    inizio_vento = 0 if ore_da_neve is None else max(0, len(serie_neve) - 1 - (ore_da_neve + 24))
    vento_serie = (f72.get("wind_speed_10m") or [])[inizio_vento:]
    vento_quota_serie = (f72.get("wind_speed_700hPa") or [])[inizio_vento:]
    vento_max = max(_max(vento_serie), _max(vento_quota_serie) * 0.8)

    # --- temperatura durante la nevicata (proxy della densita')
    temp_nevicata = _media(
        [t for t, s in zip(f72.get("temperature_2m") or [], serie_neve) if (s or 0) >= 0.3]
    )

    # --- pioggia dopo l'ultima neve: uccide tutto
    pioggia_dopo = 0.0
    if ore_da_neve is not None and ore_da_neve > 0:
        pioggia_dopo = _somma((f72.get("rain") or [])[-ore_da_neve:])
    else:
        pioggia_dopo = _somma((f24.get("rain") or []))

    # ------------------------------------------------------------ punteggio
    punteggio = min(5.0, neve72 / 12.0)  # 60 cm in 72h = 5
    fattori: list[str] = []
    if neve72 > 0:
        fattori.append(f"{neve72:.0f} cm in 72h ({neve24:.0f} nelle ultime 24h)")

    if vento_max >= 60:
        punteggio -= 2.0
        fattori.append(f"vento forte ({vento_max:.0f} km/h): neve trasportata e crosta da vento")
    elif vento_max >= 40:
        punteggio -= 1.2
        fattori.append(f"vento sostenuto ({vento_max:.0f} km/h)")
    elif vento_max >= 25:
        punteggio -= 0.6
        fattori.append(f"vento moderato ({vento_max:.0f} km/h)")
    else:
        fattori.append(f"vento debole ({vento_max:.0f} km/h)")

    if temp_nevicata is not None:
        if temp_nevicata > 0:
            punteggio -= 1.5
            fattori.append(f"nevicata a {temp_nevicata:.0f}C: neve umida e pesante")
        elif temp_nevicata > -2:
            punteggio -= 0.6
            fattori.append(f"nevicata attorno a {temp_nevicata:.0f}C")
        elif temp_nevicata < -6:
            punteggio += 0.3
            fattori.append(f"nevicata fredda ({temp_nevicata:.0f}C): neve leggera")

    if ore_da_neve is None:
        punteggio = min(punteggio, 0.5)
        fattori.append("nessuna nevicata nelle ultime 72h")
    elif ore_da_neve <= 18:
        fattori.append(f"ultima neve {ore_da_neve}h fa")
    elif ore_da_neve <= 48:
        punteggio -= 0.5
        fattori.append(f"ultima neve {ore_da_neve}h fa")
    else:
        punteggio -= 1.2
        fattori.append(f"ultima neve {ore_da_neve}h fa: probabile rimaneggiata o crosta")

    crosta_pioggia = pioggia_dopo >= 2
    if crosta_pioggia:
        punteggio = min(punteggio, 1.0)
        fattori.append(f"pioggia dopo la neve ({pioggia_dopo:.0f} mm): crosta")

    punteggio = max(0.0, min(5.0, punteggio))

    # ------------------------------------------------- avviso valanghe onesto
    avviso = None
    if neve48 >= 20 and vento_max >= 30:
        avviso = (
            "Neve fresca abbondante con vento: sono le condizioni tipiche di formazione "
            "dei lastroni. Leggi il bollettino valanghe prima di decidere."
        )
    elif neve48 >= 30:
        avviso = (
            "Nevicata importante nelle ultime 48h: il pericolo valanghe sale sempre "
            "durante e subito dopo una nevicata."
        )

    return {
        "punteggio": round(punteggio, 1),
        "fiocchi": int(round(punteggio)),
        "neve_24h_cm": round(neve24, 1),
        "neve_48h_cm": round(neve48, 1),
        "neve_72h_cm": round(neve72, 1),
        "vento_max_kmh": round(vento_max),
        "temp_nevicata": round(temp_nevicata, 1) if temp_nevicata is not None else None,
        "ore_da_ultima_neve": ore_da_neve,
        "crosta_da_pioggia": crosta_pioggia,
        "fattori": fattori,
        "avviso_valanghe": avviso,
    }


def etichetta(punteggio: float | None) -> str:
    if punteggio is None:
        return "dati non disponibili"
    if punteggio >= 4.5:
        return "powder"
    if punteggio >= 3.5:
        return "molto buona"
    if punteggio >= 2.5:
        return "buona"
    if punteggio >= 1.5:
        return "discreta"
    if punteggio >= 0.5:
        return "trasformata o crosta"
    return "niente neve fresca"
