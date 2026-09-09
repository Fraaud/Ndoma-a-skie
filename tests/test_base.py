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
from app.services import neve, valanghe  # noqa: E402


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


# ----------------------------------------------------------------- neve

def test_niente_neve():
    n = neve.nevicato(meteo_finto(), dt.date.today())
    assert n["ha_nevicato"] is False
    assert n["neve_72h_cm"] == 0.0
    assert n["avvertenza"] is None
    assert "nessuna nevicata" in n["descrizione"]


def test_riporta_i_centimetri_caduti():
    nevicata = {i: 3.0 for i in range(10, 24)}          # ~42 cm fra 24 e 10 ore fa
    n = neve.nevicato(meteo_finto(nevicata=nevicata), dt.date.today())
    assert n["ha_nevicato"] is True
    assert 40 <= n["neve_72h_cm"] <= 45
    assert n["ore_da_ultima_neve"] == 10
    assert "cm nelle ultime 72 ore" in n["descrizione"]


def test_con_neve_fresca_l_avvertenza_c_e_sempre():
    """Regola non negoziabile: se ha nevicato, l'avvertenza accompagna il dato.
    E' un richiamo generale, non un giudizio sull'itinerario."""
    nevicata = {i: 3.0 for i in range(10, 24)}
    n = neve.nevicato(meteo_finto(nevicata=nevicata), dt.date.today())
    assert n["avvertenza"]
    assert "bollettino" in n["avvertenza"].lower()


def test_nessun_punteggio_e_nessun_giudizio():
    """Non si calcola nessun indice nostro: solo quantita' misurate.
    Se qualcuno rimette un punteggio o un'etichetta di qualita', qui fallisce."""
    nevicata = {i: 3.0 for i in range(10, 24)}
    n = neve.nevicato(meteo_finto(nevicata=nevicata, vento=70), dt.date.today())
    for proibito in ("punteggio", "etichetta", "fiocchi", "qualita"):
        assert not any(proibito in k for k in n), f"non deve esserci '{proibito}'"
    assert not hasattr(neve, "calcola")


def test_il_vento_non_cambia_i_centimetri():
    """Il vento non entra piu' nel dato: e' un'informazione meteo, non una
    correzione nostra della neve caduta."""
    nevicata = {i: 3.0 for i in range(10, 24)}
    calmo = neve.nevicato(meteo_finto(nevicata=nevicata, vento=5), dt.date.today())
    ventoso = neve.nevicato(meteo_finto(nevicata=nevicata, vento=70), dt.date.today())
    assert calmo["neve_72h_cm"] == ventoso["neve_72h_cm"]


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


def test_normalizza_esposizioni_niente_giudizi():
    """Di valanghe restano solo lettura e normalizzazione del bollettino:
    nessuna funzione che incroci il bollettino con i dati della gita."""
    assert not hasattr(valanghe, "evidenzia")


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
