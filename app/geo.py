"""Utilita' geografiche: comuni, micro-regioni valanghe, mercatore.

Carica i GeoJSON una volta sola in memoria (sono pochi MB) e offre
point-in-polygon e intersezione linea/poligoni con shapely.
"""
from __future__ import annotations

import json
import math
import os
from functools import lru_cache
from typing import Any, Iterable

from shapely.geometry import LineString, Point, shape
from shapely.strtree import STRtree

from app.config import settings

# ---------------------------------------------------------------- proiezioni


def mercator_to_wgs84(x: float, y: float) -> tuple[float, float]:
    """EPSG:3857 (metri) -> (lon, lat). Camptocamp restituisce le geometrie cosi'."""
    lon = x / 20037508.34 * 180.0
    lat = y / 20037508.34 * 180.0
    lat = 180.0 / math.pi * (2.0 * math.atan(math.exp(lat * math.pi / 180.0)) - math.pi / 2.0)
    return lon, lat


def distanza_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def dentro_bbox(lon: float, lat: float, bbox=None) -> bool:
    b = bbox or settings.bbox
    return b[0] <= lon <= b[2] and b[1] <= lat <= b[3]


def istat_a_sei(valore) -> str | None:
    """Riporta un codice ISTAT alla forma canonica: sei cifre con gli zeri.

    Il GeoJSON dei comuni porta lo STESSO codice in due formati:
        com_istat_code      "004078"   (stringa, con gli zeri davanti)
        com_istat_code_num   4078      (numero, senza)
    Finivano in posti diversi - l'indice spaziale leggeva il numero, la
    tabella dei comuni la stringa - e siccome il confronto e' fra stringhe,
    "4078" e "004078" non sono mai uguali. Conseguenza: la regola piu'
    importante del match, "il passeggero e' SULLA STRADA di chi guida", non
    poteva scattare mai, e i paesi attraversati comparivano come numeri
    invece che come nomi. Un errore silenzioso: nessun crash, nessun log,
    solo match che non arrivano.

    Da qui in poi il formato canonico e' uno: sei cifre. Codici che non sono
    numerici (o piu' lunghi) si lasciano stare: non sono codici ISTAT.
    """
    if valore is None or valore == "":
        return None
    t = str(valore).strip()
    return t.zfill(6) if t.isdigit() and len(t) <= 6 else t


# ------------------------------------------------------------- indice spaziale


class IndiceGeo:
    """Indice spaziale su un FeatureCollection, con lookup per punto e per linea."""

    def __init__(self, path: str, chiavi: dict[str, list[str]]):
        self.path = path
        self.chiavi = chiavi  # nome_logico -> lista di possibili proprieta' nel geojson
        self.geoms: list[Any] = []
        self.props: list[dict] = []
        self.tree: STRtree | None = None
        if os.path.exists(path):
            self._carica()

    def _carica(self) -> None:
        with open(self.path, "r", encoding="utf-8") as f:
            gj = json.load(f)
        for feat in gj.get("features", []):
            geom = feat.get("geometry")
            if not geom:
                continue
            try:
                g = shape(geom)
            except Exception:
                continue
            if g.is_empty:
                continue
            self.geoms.append(g)
            self.props.append(feat.get("properties", {}) or {})
        if self.geoms:
            self.tree = STRtree(self.geoms)

    @property
    def disponibile(self) -> bool:
        return self.tree is not None

    def _estrai(self, props: dict) -> dict:
        out = {}
        for logico, candidati in self.chiavi.items():
            for c in candidati:
                if c in props and props[c] not in (None, ""):
                    out[logico] = props[c]
                    break
            else:
                out[logico] = None
        # I codici ISTAT escono da qui in forma canonica, sempre. E' il punto
        # in cui entrano nel programma, quindi e' il punto giusto: normalizzare
        # piu' a valle vuol dire dimenticarsene in un posto su tre.
        if "istat" in out:
            out["istat"] = istat_a_sei(out["istat"])
        return out

    def per_punto(self, lat: float, lon: float) -> dict | None:
        if not self.tree:
            return None
        p = Point(lon, lat)
        for idx in self.tree.query(p):
            if self.geoms[idx].contains(p):
                return self._estrai(self.props[idx])
        return None

    def attraversati(self, coords: Iterable[tuple[float, float]]) -> list[dict]:
        """coords = sequenza (lon, lat). Restituisce le feature attraversate,
        nell'ordine in cui la linea le incontra."""
        if not self.tree:
            return []
        punti = list(coords)
        if len(punti) < 2:
            return []
        linea = LineString(punti)
        candidati = self.tree.query(linea)
        trovati: list[tuple[float, dict]] = []
        for idx in candidati:
            g = self.geoms[idx]
            if not g.intersects(linea):
                continue
            # posizione lungo il percorso, per ordinare i comuni dal partente all'attacco
            try:
                pezzo = g.intersection(linea)
                rappresentativo = pezzo.representative_point() if not pezzo.is_empty else g.centroid
                dist = linea.project(rappresentativo)
            except Exception:
                dist = linea.project(g.centroid)
            trovati.append((dist, self._estrai(self.props[idx])))
        trovati.sort(key=lambda t: t[0])
        return [p for _, p in trovati]


@lru_cache
def indice_comuni() -> IndiceGeo:
    return IndiceGeo(
        settings.comuni_geojson,
        {
            "istat": ["com_istat_code_num", "com_istat_code", "pro_com_t", "PRO_COM_T", "istat"],
            "nome": ["name", "COMUNE", "comune", "nome"],
            "provincia": ["prov_name", "DEN_UTS", "provincia"],
            "regione": ["reg_name", "DEN_REG", "regione"],
        },
    )


@lru_cache
def indice_eaws() -> IndiceGeo:
    return IndiceGeo(
        settings.eaws_regions_geojson,
        {
            "id": ["id", "region_id", "ID"],
            "nome": ["name", "name_it", "name_en", "NAME"],
            "start_date": ["start_date"],
        },
    )


def comune_di(lat: float, lon: float) -> dict | None:
    return indice_comuni().per_punto(lat, lon)


def regione_eaws_di(lat: float, lon: float) -> str | None:
    r = indice_eaws().per_punto(lat, lon)
    return r.get("id") if r else None
