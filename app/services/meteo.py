"""Meteo da Open-Meteo: gratuito per uso non commerciale, senza API key.

Chiediamo sempre anche i giorni passati: la qualita' della neve di sabato
dipende da cosa e' successo da mercoledi' in poi.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

import httpx

from app.config import settings

ORARIE = [
    "temperature_2m",
    "precipitation",
    "rain",
    "snowfall",
    "snow_depth",
    "freezing_level_height",
    "wind_speed_10m",
    "wind_gusts_10m",
    "wind_direction_10m",
]
# Vento in quota: utilissimo per capire il trasporto eolico. Non tutti i
# modelli lo espongono, quindi se la chiamata fallisce si riprova senza.
ORARIE_QUOTA = ["wind_speed_700hPa", "wind_direction_700hPa", "temperature_700hPa"]

# "sunset" non e' decorazione: e' il dato piu' utile della schermata
# Emergenza, e va scaricato PRIMA - insieme alla scheda - perche' quando
# serve, in valle, il telefono e' probabilmente senza campo.
GIORNALIERE = ["temperature_2m_max", "temperature_2m_min", "snowfall_sum",
               "precipitation_sum", "sunrise", "sunset"]


async def previsioni(
    lat: float,
    lon: float,
    quota: int | None = None,
    giorni_passati: int = 4,
    giorni_previsti: int = 7,
    modello: str = "best_match",
) -> dict[str, Any]:
    """Serie oraria e giornaliera per un punto. `quota` corregge il downscaling
    (l'attacco a 1600 m dentro una cella da 2 km fa una gran differenza)."""
    params: dict[str, Any] = {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "hourly": ",".join(ORARIE + ORARIE_QUOTA),
        "daily": ",".join(GIORNALIERE),
        "past_days": giorni_passati,
        "forecast_days": giorni_previsti,
        "timezone": "Europe/Rome",
        "models": modello,
    }
    if quota:
        params["elevation"] = int(quota)

    async with httpx.AsyncClient(timeout=25, headers={"User-Agent": settings.user_agent}) as c:
        r = await c.get(settings.url_open_meteo, params=params)
        if r.status_code == 400:
            # probabile variabile non supportata dal modello: riprova senza i livelli di pressione
            params["hourly"] = ",".join(ORARIE)
            r = await c.get(settings.url_open_meteo, params=params)
        if r.status_code == 400:
            # ultimo tentativo: solo le giornaliere storiche. Meglio una
            # scheda senza tramonto che una scheda senza meteo.
            params["daily"] = ",".join(
                v for v in GIORNALIERE if v not in ("sunrise", "sunset"))
            r = await c.get(settings.url_open_meteo, params=params)
        r.raise_for_status()
        return r.json()


def _indice_ora(times: list[str], quando: dt.datetime) -> int:
    """Indice dell'ora piu' vicina a `quando` nella serie Open-Meteo.

    La serie e' oraria e continua, quindi la posizione si calcola con una
    sottrazione invece di cercarla. Non e' pignoleria: la scheda gita chiama
    questa funzione una sessantina di volte, e la ricerca lineare su 240
    elementi con una conversione di data per confronto costava piu' di tutto
    il resto della pagina messo insieme.
    """
    if not times:
        raise ValueError("serie oraria vuota")
    inizio = dt.datetime.fromisoformat(times[0])
    quando = quando.replace(tzinfo=None)
    i = round((quando - inizio).total_seconds() / 3600)
    i = max(0, min(len(times) - 1, i))
    # verifica: se l'aritmetica non torna (buchi nella serie) si ripiega
    atteso = quando.strftime("%Y-%m-%dT%H:00")
    if times[i] == atteso:
        return i
    try:
        return times.index(atteso)
    except ValueError:
        return i


def finestra(dati: dict, quando: dt.datetime, ore_prima: int) -> dict[str, list]:
    """Estrae le serie orarie nelle `ore_prima` ore precedenti a `quando`."""
    h = dati.get("hourly", {})
    times = h.get("time", [])
    if not times:
        return {}
    fine = _indice_ora(times, quando)
    inizio = max(0, fine - ore_prima)
    out = {"time": times[inizio : fine + 1]}
    for k, v in h.items():
        if k == "time" or not isinstance(v, list):
            continue
        out[k] = v[inizio : fine + 1]
    return out


def valore_a(dati: dict, quando: dt.datetime, variabile: str):
    h = dati.get("hourly", {})
    times, serie = h.get("time", []), h.get(variabile)
    if not times or not serie:
        return None
    return serie[_indice_ora(times, quando)]


def sintesi_giorno(dati: dict, giorno: dt.date) -> dict[str, Any]:
    """Riquadro meteo per la scheda gita: mattina presto e met� giornata."""
    alba = dt.datetime.combine(giorno, dt.time(7, 0))
    mezzo = dt.datetime.combine(giorno, dt.time(12, 0))
    d = dati.get("daily", {})
    idx = d.get("time", []).index(giorno.isoformat()) if giorno.isoformat() in d.get("time", []) else None
    return {
        "giorno": giorno.isoformat(),
        "temp_attacco_7": valore_a(dati, alba, "temperature_2m"),
        "temp_attacco_12": valore_a(dati, mezzo, "temperature_2m"),
        "temp_min": d.get("temperature_2m_min", [None])[idx] if idx is not None else None,
        "temp_max": d.get("temperature_2m_max", [None])[idx] if idx is not None else None,
        "neve_prevista_cm": d.get("snowfall_sum", [None])[idx] if idx is not None else None,
        "quota_zero": valore_a(dati, mezzo, "freezing_level_height"),
        "vento_kmh": valore_a(dati, mezzo, "wind_speed_10m"),
        "raffica_kmh": valore_a(dati, mezzo, "wind_gusts_10m"),
        "vento_dir": valore_a(dati, mezzo, "wind_direction_10m"),
        "vento_quota_kmh": valore_a(dati, mezzo, "wind_speed_700hPa"),
        "neve_al_suolo_cm": (valore_a(dati, mezzo, "snow_depth") or 0) * 100,
        # solo l'ora, non la data: e' quello che si legge in Emergenza
        "tramonto": _ora(d.get("sunset", []), idx),
        "alba": _ora(d.get("sunrise", []), idx),
    }


def _ora(serie: list, idx: int | None) -> str | None:
    """"2026-02-14T17:42" -> "17:42". None se il dato non c'e'."""
    if idx is None or idx >= len(serie or []):
        return None
    v = serie[idx]
    return str(v)[11:16] if v else None
