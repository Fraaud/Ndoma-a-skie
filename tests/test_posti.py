"""Parcheggi, ripari e piole.

Il campo che conta piu' di tutti e' `capacity` sui parcheggi: l'app e' nata
da sei macchine ferme in un piazzale. In OSM pero' quel campo e' scritto a
mano da qualcuno, e nella realta' non e' sempre un numero - quindi la meta'
di questo file verifica che una capienza scritta male diventi "non
indicata" invece di far cadere l'import o, peggio, di diventare un numero
inventato.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import sys
import time
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import posti  # noqa: E402
from app.db import SessionLocal, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Comune, Gita, Percorso, Posto  # noqa: E402
from importers import posti as importatore  # noqa: E402

TOKEN = "123456:TESTTOKEN"


def intestazione(tg_id: int, nome: str = "Test") -> dict:
    campi = {"auth_date": str(int(time.time())),
             "user": json.dumps({"id": tg_id, "first_name": nome})}
    dcs = "\n".join(f"{k}={campi[k]}" for k in sorted(campi))
    segreto = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    campi["hash"] = hmac.new(segreto, dcs.encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urlencode(campi)}


# ------------------------------------------------------------- la capienza


def test_una_capienza_scritta_a_mano_diventa_un_numero_o_niente():
    assert posti.capienza({"capacity": "12"}) == 12
    assert posti.capienza({"capacity": "~20"}) == 20
    assert posti.capienza({"capacity": "10;5"}) == 10
    assert posti.capienza({"capacity": "circa 30 posti"}) == 30
    # "yes" vuol dire "c'e' un parcheggio", non "c'e' un posto"
    assert posti.capienza({"capacity": "yes"}) is None
    assert posti.capienza({"capacity": ""}) is None
    assert posti.capienza({}) is None
    # un numero assurdo e' un errore di battitura, non un piazzale
    assert posti.capienza({"capacity": "99999"}) is None
    assert posti.capienza({"capacity": "0"}) is None


def test_la_capienza_non_indicata_si_dice_invece_di_sparire():
    """Un parcheggio senza capienza si mostra comunque: esiste."""
    class Finto:
        tipo = "parcheggio"
        capienza = None
    assert posti.capienza_in_parole(Finto()) == "capienza non indicata"
    Finto.capienza = 1
    assert posti.capienza_in_parole(Finto()) == "1 posto"
    Finto.capienza = 24
    assert posti.capienza_in_parole(Finto()) == "24 posti"


def test_la_quota_fuori_scala_si_scarta():
    assert posti.quota({"ele": "1638"}) == 1638
    assert posti.quota({"ele": "1638.5 m"}) == 1638
    assert posti.quota({"ele": "circa"}) is None
    assert posti.quota({"ele": "99000"}) is None


# ---------------------------------------------------------- classificazione


def test_si_riconosce_che_cosa_e():
    assert posti.classifica({"amenity": "parking"}) == "parcheggio"
    assert posti.classifica({"tourism": "alpine_hut"}) == "riparo"
    assert posti.classifica({"tourism": "wilderness_hut"}) == "riparo"
    assert posti.classifica({"amenity": "shelter"}) == "riparo"
    assert posti.classifica({"amenity": "restaurant"}) == "piola"
    assert posti.classifica({"amenity": "pharmacy"}) is None


def test_una_pensilina_dellautobus_non_e_un_riparo_di_montagna():
    """In Emergenza sarebbe un consiglio sbagliato: in OSM le fermate sono
    taggate `amenity=shelter` esattamente come i ripari veri."""
    assert posti.classifica({"amenity": "shelter",
                             "shelter_type": "public_transport"}) is None
    assert posti.classifica({"amenity": "shelter",
                             "shelter_type": "basic_hut"}) == "riparo"


def test_un_parcheggio_privato_non_e_un_parcheggio():
    for accesso in ("private", "no", "customers", "permit"):
        assert posti.utilizzabile("parcheggio", {"access": accesso}) is False
    assert posti.utilizzabile("parcheggio", {"access": "yes"}) is True
    assert posti.utilizzabile("parcheggio", {}) is True
    # sulle piole non si filtra: un ristorante e' per definizione "customers"
    assert posti.utilizzabile("piola", {"access": "customers"}) is True


def test_il_bivacco_si_distingue_dal_rifugio_gestito():
    """Quando sta venendo buio, la differenza e' tutto."""
    assert posti.genere("riparo", {"tourism": "wilderness_hut"}) == "bivacco, non gestito"
    assert posti.genere("riparo", {"tourism": "alpine_hut"}) == "rifugio gestito"


# -------------------------------------------------- lettura degli elementi


def test_un_elemento_overpass_diventa_un_posto():
    e = {"type": "node", "id": 42, "lat": 44.16, "lon": 7.79,
         "tags": {"amenity": "parking", "capacity": "18", "fee": "no",
                  "ele": "1380", "name": "Piazzale di Carnino"}}
    d = posti.da_elemento(e)
    assert d["tipo"] == "parcheggio" and d["capienza"] == 18
    assert d["fonte_id"] == "node/42" and d["quota"] == 1380
    assert d["dettagli"] == {"fee": "no"}


def test_un_way_prende_il_centro():
    e = {"type": "way", "id": 7, "center": {"lat": 44.2, "lon": 7.5},
         "tags": {"amenity": "parking"}}
    d = posti.da_elemento(e)
    assert (d["lat"], d["lon"]) == (44.2, 7.5)
    assert d["fonte_id"] == "way/7"


def test_gli_elementi_rotti_non_fanno_cadere_limport():
    """E' l'unico punto in cui entrano dati di forma non nostra."""
    for e in ({}, None, "boh", {"type": "way", "id": 1, "tags": {"amenity": "parking"}},
              {"type": "node", "id": 2, "lat": "x", "lon": "y",
               "tags": {"amenity": "parking"}},
              {"type": "node", "id": 3, "lat": 44.1, "lon": 7.1, "tags": None},
              {"type": "node", "id": 4, "lat": 44.1, "lon": 7.1,
               "tags": {"amenity": "pharmacy"}}):
        assert posti.da_elemento(e) is None


def test_una_piola_senza_nome_non_serve_a_nessuno():
    e = {"type": "node", "id": 9, "lat": 44.3, "lon": 7.6,
         "tags": {"amenity": "bar"}}
    assert posti.da_elemento(e) is None
    e["tags"]["name"] = "Bar della Posta"
    assert posti.da_elemento(e)["tipo"] == "piola"


def test_gli_orari_di_apertura_non_li_teniamo():
    """OSM li ha, ma nelle valli sono vecchi di anni: far credere a qualcuno
    che una piola e' aperta e' peggio che non dirgli niente."""
    e = {"type": "node", "id": 11, "lat": 44.3, "lon": 7.6,
         "tags": {"amenity": "restaurant", "name": "Da Meo",
                  "opening_hours": "Mo-Su 12:00-14:00", "phone": "+39 0171 1"}}
    d = posti.da_elemento(e)
    assert "opening_hours" not in d["dettagli"]
    assert d["dettagli"]["phone"] == "+39 0171 1"


# ------------------------------------------------- il filtro sulla vicinanza


def test_i_parcheggi_lontani_da_ogni_gita_si_scartano():
    """Senza questo filtro importeremmo tutti i parcheggi di Cuneo."""
    griglia = {}
    for lat, lon in [(44.16, 7.79)]:
        griglia.setdefault(importatore._cella(lat, lon), []).append((lat, lon))
    # a duecento metri dall'attacco: e' il parcheggio della gita
    assert importatore.vicino_a_una_gita(44.1618, 7.7902, griglia, 2.0) is True
    # a Cuneo, cinquanta chilometri piu' in la'
    assert importatore.vicino_a_una_gita(44.39, 7.55, griglia, 2.0) is False


# --------------------------------------------------------------------- API


@pytest.fixture()
def mondo():
    """Una gita, il suo parcheggio, un bivacco e due piole in fondovalle."""
    Base.metadata.drop_all(engine)
    init_db()
    s = SessionLocal()
    g = Gita(nome="Cima delle Saline", fonte="test", fonte_id="1",
             lat=44.160, lon=7.790, quota_min=1380)
    s.add_all([
        g,
        Comune(istat="004078", nome="Cuneo", provincia="Cuneo", lat=44.39, lon=7.55),
        Comune(istat="004010", nome="Bagnasco", provincia="Cuneo", lat=44.30, lon=7.98),
        Posto(tipo="parcheggio", fonte="osm", fonte_id="node/1",
              nome="Piazzale di Carnino", lat=44.1615, lon=7.7905,
              capienza=18, quota=1380, istat="004010", dettagli={"fee": "no"}),
        Posto(tipo="parcheggio", fonte="osm", fonte_id="node/2",
              nome=None, lat=44.150, lon=7.780, capienza=None, istat="004010"),
        # a venti chilometri: non deve comparire nella scheda
        Posto(tipo="parcheggio", fonte="osm", fonte_id="node/3",
              nome="Parcheggio di Cuneo", lat=44.39, lon=7.55, capienza=200,
              istat="004078"),
        Posto(tipo="riparo", fonte="osm", fonte_id="node/4",
              nome="Rifugio Mondovi'", lat=44.1700, lon=7.8000,
              genere="rifugio gestito", quota=1760, istat="004010"),
        Posto(tipo="piola", fonte="osm", fonte_id="node/5", nome="Da Meo",
              lat=44.30, lon=7.98, genere="ristorante", istat="004010",
              dettagli={"phone": "+39 0171 1"}),
        Posto(tipo="piola", fonte="osm", fonte_id="node/6", nome="Bar Centrale",
              lat=44.39, lon=7.55, genere="bar", istat="004078"),
    ])
    s.commit()
    gid = g.id
    s.close()
    return TestClient(app), gid


def test_la_scheda_mostra_il_parcheggio_con_la_capienza(mondo):
    c, gid = mondo
    d = c.get(f"/api/posti/{gid}").json()
    nomi = [p["etichetta"] for p in d["parcheggi"]]
    assert "Piazzale di Carnino" in nomi
    assert "Parcheggio di Cuneo" not in nomi          # troppo lontano
    primo = d["parcheggi"][0]
    assert primo["capienza"] == 18
    assert primo["capienza_testo"] == "18 posti"
    assert primo["distanza_m"] <= 200
    assert "OpenStreetMap" in d["attribuzione"]


def test_un_parcheggio_senza_nome_si_mostra_comunque(mondo):
    c, gid = mondo
    d = c.get(f"/api/posti/{gid}").json()
    senza = [p for p in d["parcheggi"] if p["nome"] is None]
    assert senza and senza[0]["etichetta"] == "Parcheggio senza nome"
    assert senza[0]["capienza_testo"] == "capienza non indicata"


def test_i_parcheggi_arrivano_dal_piu_vicino(mondo):
    c, gid = mondo
    d = c.get(f"/api/posti/{gid}").json()
    distanze = [p["distanza_km"] for p in d["parcheggi"]]
    assert distanze == sorted(distanze)


def test_i_ripari_arrivano_con_la_scheda_anche_se_nessuno_li_ha_chiesti(mondo):
    """Servono in Emergenza, e in Emergenza il telefono e' senza campo:
    l'unico momento per scaricarli e' adesso."""
    c, gid = mondo
    d = c.get(f"/api/posti/{gid}").json()
    assert d["ripari"] and d["ripari"][0]["nome"] == "Rifugio Mondovi'"
    assert d["ripari"][0]["genere"] == "rifugio gestito"


def test_lavvertenza_dice_che_le_distanze_sono_in_linea_daria(mondo):
    c, gid = mondo
    t = c.get(f"/api/posti/{gid}").json()["avvertenza"].lower()
    assert "linea d'aria" in t
    assert "vecchia" in t          # la capienza di OSM puo' essere vecchia


def test_una_gita_che_non_esiste_da_404(mondo):
    c, _ = mondo
    assert c.get("/api/posti/99999").status_code == 404


def test_le_piole_stanno_lungo_il_ritorno_non_vicino_allattacco(mondo):
    """Il test che spiega la scelta: a 1600 m, a marzo, non c'e' niente di
    aperto. La piola dove ci si ferma e' in fondovalle, sulla strada di casa,
    ed e' il corridoio che calcoliamo gia' per i passaggi."""
    c, gid = mondo
    c.put("/api/profilo", headers=intestazione(6001),
          json={"comune_partenza": "Cuneo", "istat_partenza": "004078"})
    s = SessionLocal()
    s.add(Percorso(istat_partenza="004078", gita_id=gid, km=60.0, minuti=75.0,
                   comuni_istat=["004078", "004010"]))
    s.commit()
    s.close()

    d = c.get(f"/api/avvicinamento/{gid}", headers=intestazione(6001)).json()
    assert d["stato"] == "pronto"
    nomi = [p["nome"] for p in d["piole"]]
    assert "Da Meo" in nomi and "Bar Centrale" in nomi
    # ordine del RITORNO: prima Bagnasco (vicino alla gita), poi Cuneo (casa)
    assert nomi.index("Da Meo") < nomi.index("Bar Centrale")
    assert d["piole"][0]["comune"] == "Bagnasco"


def test_senza_percorso_non_si_inventano_le_piole(mondo):
    c, gid = mondo
    d = c.get(f"/api/avvicinamento/{gid}", headers=intestazione(6002)).json()
    assert d["stato"] == "senza_comune"
    assert "piole" not in d
