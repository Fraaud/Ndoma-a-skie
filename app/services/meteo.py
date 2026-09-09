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

GIORNALIERE = ["temperature_2m_max", "temperature_2m_min", "snowfall_sum", "precipitation_sum"]


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
        r.raise_for_status()
        return r.json()


def _indice_ora(times: list[str], quando: dt.datetime) -> int:
    """Indice dell'ora piu' vicina a `quando` nella serie Open-Meteo."""
    target = quando.strftime("%Y-%m-%dT%H:00")
    if target in times:
        return times.index(target)
    # fallback: la piu' vicina
    migliori = min(
        range(len(times)),
        key=lambda i: abs(dt.datetime.fromisoformat(times[i]) - quando.replace(tzinfo=None)),
    )
    return migliori


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
    }
