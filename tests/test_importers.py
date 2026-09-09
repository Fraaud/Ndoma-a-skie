"""Test dei parser degli importatori.

Nascono da un errore vero: la geometria di Camptocamp ha DUE forme diverse a
seconda dell'endpoint, e leggerne una sola sola faceva importare zero gite
senza dare nessun errore. Questi test bloccano quel tipo di sbaglio.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.geo import mercator_to_wgs84  # noqa: E402
from importers.camptocamp import _coordinate, _titolo, wgs84_to_mercator  # noqa: E402

# Pontebernardo, alta Valle Stura
LAT, LON = 44.34, 7.02


def _merc():
    return wgs84_to_mercator(LON, LAT)


def test_conversione_andata_e_ritorno():
    x, y = _merc()
    lon, lat = mercator_to_wgs84(x, y)
    assert abs(lat - LAT) < 1e-6
    assert abs(lon - LON) < 1e-6


def test_geometria_forma_elenco():
    """L'endpoint /routes restituisce GeoJSON diretto."""
    x, y = _merc()
    p = _coordinate({"type": "Point", "coordinates": [x, y]})
    assert p is not None
    assert abs(p[0] - LAT) < 1e-5 and abs(p[1] - LON) < 1e-5


def test_geometria_forma_dettaglio():
    """L'endpoint /routes/{id} restituisce una stringa JSON dentro 'geom'."""
    x, y = _merc()
    p = _coordinate({"geom": json.dumps({"type": "Point", "coordinates": [x, y]})})
    assert p is not None
    assert abs(p[0] - LAT) < 1e-5 and abs(p[1] - LON) < 1e-5


def test_geometria_linestring():
    x, y = _merc()
    p = _coordinate({"type": "LineString", "coordinates": [[x, y], [x + 100, y + 100]]})
    assert p is not None and abs(p[0] - LAT) < 1e-5


def test_geometria_assente_o_rotta():
    assert _coordinate(None) is None
    assert _coordinate({}) is None
    assert _coordinate({"geom": "non e' json"}) is None
    assert _coordinate({"type": "Polygon"}) is None


def test_titolo_con_prefisso():
    doc = {"locales": [{"title": "Testa Malacosta", "title_prefix": "Cima"}]}
    assert _titolo(doc) == "Cima - Testa Malacosta"
    assert _titolo({"locales": [{"title": "Solo titolo"}]}) == "Solo titolo"
    assert _titolo({"locales": []}) is None
