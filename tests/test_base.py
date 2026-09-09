"""Test che girano senza rete: powder score, match, auth.

  pytest -q
"""
from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest  # noqa: E402

from app.auth import verifica_init_data  # noqa: E402
from app.services import powder, valanghe  # noqa: E402


# --------------------------------------------------------------- helper

def meteo_finto(ore: int = 120, nevicata=None, vento=5.0, temp=-5.0, pioggia=None) -> dict:
    """Serie oraria sintetica. `nevicata` = {ora_relativa_dalla_fine: cm}."""
    fine = dt.datetime.combine(dt.date.today(), dt.time(8, 0))
    tempi, neve, venti, temperature, piogge = [], [], [], [], []
    for i in range(ore, -1, -1):
        t = fine - dt.timedelta(hours=i)
        tempi.append(t.strftime("%Y-%m-%dT%H:00"))
        neve.append((nevicata or {}).get(i, 0.0))
        piogge.append((pioggia or {}).get(i, 0.0))
        venti.append(vento)
        temperature.append(temp)
    return {
        "hourly": {
            "time": tempi, "snowfall": neve, "rain": piogge,
            "wind_speed_10m": venti, "temperature_2m": temperature,
            "snow_depth": [0.5] * len(tempi),
            "freezing_level_height": [1500] * len(tempi),
            "wind_gusts_10m": [v * 1.5 for v in venti],
            "wind_direction_10m": [270] * len(tempi),
        },
        "daily": {"time": [dt.date.today().isoformat()], "temperature_2m_min": [-8],
                  "temperature_2m_max": [-2], "snowfall_sum": [10], "precipitation_sum": [8]},
    }


# --------------------------------------------------------------- powder

def test_niente_neve_punteggio_zero():
    p = powder.calcola(meteo_finto(), dt.date.today())
    assert p["punteggio"] == 0.0
    assert p["ore_da_ultima_neve"] is None


def test_nevicata_fredda_senza_vento_e_powder():
    nevicata = {i: 3.0 for i in range(10, 24)}  # ~42 cm fra 24 e 10 ore fa
    p = powder.calcola(meteo_finto(nevicata=nevicata, vento=8, temp=-8), dt.date.today())
    assert p["punteggio"] >= 3.5
    assert p["neve_72h_cm"] > 35
    assert powder.etichetta(p["punteggio"]) in ("powder", "molto buona")


def test_il_vento_forte_abbassa_il_punteggio():
    nevicata = {i: 3.0 for i in range(10, 24)}
    calmo = powder.calcola(meteo_finto(nevicata=nevicata, vento=8), dt.date.today())
    ventoso = powder.calcola(meteo_finto(nevicata=nevicata, vento=70), dt.date.today())
    assert ventoso["punteggio"] < calmo["punteggio"]


def test_neve_e_vento_generano_avviso_valanghe():
    """Il punto piu' importante di tutto il file: tanta neve piu' vento deve
    SEMPRE produrre l'avviso, anche (soprattutto) se il powder score e' alto."""
    nevicata = {i: 3.0 for i in range(10, 24)}
    p = powder.calcola(meteo_finto(nevicata=nevicata, vento=45), dt.date.today())
    assert p["avviso_valanghe"] is not None
    assert "bollettino" in p["avviso_valanghe"].lower()


def test_pioggia_dopo_la_neve_fa_crosta():
    nevicata = {i: 4.0 for i in range(40, 60)}
    pioggia = {i: 1.5 for i in range(5, 20)}
    p = powder.calcola(meteo_finto(nevicata=nevicata, pioggia=pioggia, temp=-1),
                       dt.date.today())
    assert p["crosta_da_pioggia"] is True
    assert p["punteggio"] <= 1.0


def test_neve_umida_penalizzata():
    nevicata = {i: 3.0 for i in range(10, 24)}
    fredda = powder.calcola(meteo_finto(nevicata=nevicata, temp=-8), dt.date.today())
    umida = powder.calcola(meteo_finto(nevicata=nevicata, temp=1), dt.date.today())
    assert umida["punteggio"] < fredda["punteggio"]


# ------------------------------------------------------------- valanghe

def test_normalizza_esposizioni():
    assert valanghe.normalizza_esposizioni(["N", "NE", "SW"]) == ["N", "NE", "SO"]
    assert valanghe.normalizza_esposizioni("N, NO") == ["N", "NO"]
    assert valanghe.normalizza_esposizioni(None) == []


def test_parsing_caaml():
    grezzo = {
        "regions": [{"regionID": "IT-21-CN-01"}],
        "dangerRatings": [{"mainValue": "considerable", "elevation": {"lowerBound": "2200"}}],
        "avalancheProblems": [{
            "problemType": "wind_slab",
            "aspects": ["N", "NE", "E"],
            "elevation": {"lowerBound": "2200"},
        }],
        "validTime": {"startTime": "2026-01-10T00:00:00Z"},
    }
    b = valanghe.normalizza(grezzo, fonte_url="http://esempio/x.json")
    assert b["regioni"] == ["IT-21-CN-01"]
    assert b["grado_massimo"] == 3
    assert b["problemi"][0]["tipo_it"] == "Lastroni da vento"
    assert b["problemi"][0]["esposizioni"] == ["N", "NE", "E"]


class GitaFinta:
    def __init__(self, esposizione, quota_min, quota_max):
        self.esposizione, self.quota_min, self.quota_max = esposizione, quota_min, quota_max


def test_evidenziatore_intercetta_la_gita_esposta():
    b = valanghe.normalizza({
        "regions": [{"regionID": "X"}],
        "dangerRatings": [{"mainValue": "considerable"}],
        "avalancheProblems": [{"problemType": "wind_slab", "aspects": ["N", "NE"],
                               "elevation": {"lowerBound": "2200"}}],
    })
    esposta = valanghe.evidenzia(GitaFinta("N,NE", 1600, 2900), b)
    assert esposta and esposta[0]["rilevanza"] == "alta"

    # gita interamente sotto la quota del problema: nessun avviso
    bassa = valanghe.evidenzia(GitaFinta("S", 900, 1500), b)
    assert bassa == []


def test_evidenziatore_senza_bollettino():
    assert valanghe.evidenzia(GitaFinta("N", 1000, 2000), None) == []


# ----------------------------------------------------------------- auth

def test_init_data_falso_viene_rifiutato():
    with pytest.raises(ValueError):
        verifica_init_data("user=%7B%22id%22%3A1%7D&hash=deadbeef", "123:FAKE")


def test_init_data_valido_viene_accettato():
    import hashlib
    import hmac
    import time
    from urllib.parse import urlencode

    token = "123456:TESTTOKEN"
    campi = {"auth_date": str(int(time.time())), "user": '{"id":42,"first_name":"Test"}'}
    dcs = "\n".join(f"{k}={campi[k]}" for k in sorted(campi))
    segreto = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    campi["hash"] = hmac.new(segreto, dcs.encode(), hashlib.sha256).hexdigest()

    utente = verifica_init_data(urlencode(campi), token)
    assert utente["id"] == 42


def test_init_data_scaduto():
    import hashlib
    import hmac
    from urllib.parse import urlencode

    token = "123456:TESTTOKEN"
    campi = {"auth_date": "1000000000", "user": '{"id":42}'}
    dcs = "\n".join(f"{k}={campi[k]}" for k in sorted(campi))
    segreto = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    campi["hash"] = hmac.new(segreto, dcs.encode(), hashlib.sha256).hexdigest()
    with pytest.raises(ValueError):
        verifica_init_data(urlencode(campi), token)
