"""Configurazione centrale, letta da .env."""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)


def _bbox(raw: str) -> tuple[float, float, float, float]:
    parts = [float(p) for p in raw.split(",")]
    if len(parts) != 4:
        raise ValueError("BBOX deve essere 'min_lon,min_lat,max_lon,max_lat'")
    return tuple(parts)  # type: ignore[return-value]


class Settings:
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    webapp_url: str = os.getenv("WEBAPP_URL", "http://localhost:8000")
    telegram_group_id: str = os.getenv("TELEGRAM_GROUP_ID", "")

    skitour_api_key: str = os.getenv("SKITOUR_API_KEY", "")
    ors_api_key: str = os.getenv("ORS_API_KEY", "")

    bbox = _bbox(os.getenv("BBOX", "6.55,44.00,7.95,44.75"))

    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR}/nduma.db")
    tile_url: str = os.getenv("TILE_URL", "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
    tile_attribution: str = os.getenv("TILE_ATTRIBUTION", "&copy; OpenStreetMap contributors")
    user_agent: str = os.getenv("HTTP_USER_AGENT", "nduma-a-sghie/0.1")

    # File geografici scaricati da scripts/setup_geo.py
    comuni_geojson: str = os.path.join(DATA_DIR, "comuni.geojson")
    eaws_regions_geojson: str = os.path.join(DATA_DIR, "eaws_micro_regions.geojson")

    # Sorgenti (URL configurabili: se una cambia, si tocca solo qui)
    url_comuni_it: str = (
        "https://raw.githubusercontent.com/openpolis/geojson-italy/master/"
        "geojson/limits_IT_municipalities.geojson"
    )
    url_eaws_regions_tmpl: str = (
        "https://regions.avalanches.org/micro-regions/{country}_micro-regions.geojson.json"
    )
    url_eaws_regions_latest_tmpl: str = (
        "https://regions.avalanches.org/micro-regions/latest/{country}_micro-regions.geojson.json"
    )
    url_eaws_bulletins_dir: str = "https://static.avalanche.report/eaws_bulletins/{date}/"
    url_aineva_bulletin: str = "https://bollettini.aineva.it/bulletin/latest?province={province}"
    url_open_meteo: str = "https://api.open-meteo.com/v1/forecast"
    url_camptocamp: str = "https://api.camptocamp.org"
    url_skitour: str = "https://skitour.fr/api"
    url_overpass: str = "https://overpass-api.de/api/interpreter"
    url_ors_directions: str = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"

    # Paesi EAWS da caricare: Italia-Piemonte e Francia
    eaws_countries = ["IT", "FR"]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
