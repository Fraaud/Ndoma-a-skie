"""L'elenco dei comuni deve finire in archivio, non solo nel file.

Questo test esiste per un buco vero: su Railway i due geojson arrivano gia'
pronti dal repository, quindi setup_geo.py non veniva mai lanciato e la
tabella dei comuni restava vuota. L'app partiva senza un errore, ma la
ricerca del comune di partenza non trovava niente - e senza quella non si
pubblica un'uscita.
"""
from __future__ import annotations

import json

from app.config import settings
from app.db import init_db, session_scope
from app.models import Comune
from scripts.setup_geo import popola_comuni

# Un quadratino attorno a Limone Piemonte: basta per verificare che i nomi
# delle proprieta' letti dal file siano quelli giusti.
FINTO = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"com_istat_code": "004110", "name": "Limone Piemonte",
                           "prov_name": "Cuneo", "reg_name": "Piemonte"},
            "geometry": {"type": "Polygon", "coordinates": [[
                [7.57, 44.18], [7.60, 44.18], [7.60, 44.20], [7.57, 44.20], [7.57, 44.18]]]},
        },
        {
            "type": "Feature",
            "properties": {"com_istat_code": "004087", "name": "Entracque",
                           "prov_name": "Cuneo", "reg_name": "Piemonte"},
            "geometry": {"type": "Polygon", "coordinates": [[
                [7.39, 44.22], [7.42, 44.22], [7.42, 44.25], [7.39, 44.25], [7.39, 44.22]]]},
        },
        # senza codice ISTAT: va scartata, non deve far cadere tutto
        {"type": "Feature", "properties": {"name": "Senza codice"},
         "geometry": {"type": "Point", "coordinates": [7.5, 44.2]}},
    ],
}


def test_popola_comuni_scrive_in_archivio():
    init_db()
    with session_scope() as db:
        prima = db.query(Comune).count()

    assert popola_comuni(FINTO) == 2

    with session_scope() as db:
        assert db.query(Comune).count() == prima + 2
        limone = db.get(Comune, "004110")
        assert limone.nome == "Limone Piemonte"
        assert limone.provincia == "Cuneo"
        # il centro deve cadere dentro il poligono, non a (0, 0)
        assert 44.18 <= limone.lat <= 44.20
        assert 7.57 <= limone.lon <= 7.60


def test_popola_comuni_si_puo_rilanciare():
    """Ogni avvio la richiama: non deve duplicare niente."""
    popola_comuni(FINTO)
    assert popola_comuni(FINTO) == 0


def test_popola_comuni_legge_il_file_se_non_gli_si_passa_niente(tmp_path, monkeypatch):
    percorso = tmp_path / "comuni.geojson"
    percorso.write_text(json.dumps(FINTO), encoding="utf-8")
    monkeypatch.setattr(settings, "comuni_geojson", str(percorso))
    popola_comuni()  # dal file, senza argomento
    with session_scope() as db:
        assert db.get(Comune, "004087").nome == "Entracque"


def test_senza_file_non_esplode(tmp_path, monkeypatch):
    """All'avvio il file potrebbe non esserci ancora: si torna zero."""
    monkeypatch.setattr(settings, "comuni_geojson", str(tmp_path / "manca.geojson"))
    assert popola_comuni() == 0
