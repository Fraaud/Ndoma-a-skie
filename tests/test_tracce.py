"""La traccia: provenienza, semplificazione, profilo, GPX.

Il test che conta di piu' e' `test_un_percorso_calcolato_non_e_adatto_allo_sci`.
Non e' una questione di etichette: d'inverno non si sale per il sentiero
estivo, e una linea "verosimile" su una gita di scialpinismo e' un
itinerario che nessuno ha percorso messo in mano a qualcuno in un terreno
dove la scelta della linea E' la decisione che conta.

Il secondo per importanza e' `test_lattribuzione_viaggia_dentro_il_gpx`: un
file che gira per WhatsApp e perde la provenienza e' un dato orfano, ed e'
il modo in cui i cataloghi altrui finiscono dove non dovrebbero.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import math
import os
import sys
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import tracce  # noqa: E402
from app.db import SessionLocal, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Gita, Traccia  # noqa: E402
from importers import camptocamp  # noqa: E402

TOKEN = "123456:TESTTOKEN"


def intestazione(tg_id: int, nome: str = "Test") -> dict:
    campi = {"auth_date": str(int(time.time())),
             "user": json.dumps({"id": tg_id, "first_name": nome})}
    dcs = "\n".join(f"{k}={campi[k]}" for k in sorted(campi))
    segreto = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    campi["hash"] = hmac.new(segreto, dcs.encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urlencode(campi)}


def salita(n: int = 60, lat0: float = 44.16, lon0: float = 7.79,
           q0: float = 1400, q1: float = 2600) -> list:
    """Una salita finta ma verosimile: un chilometro in diagonale, 1200 m."""
    return [[round(lat0 + 0.004 * i / n, 6), round(lon0 + 0.006 * i / n, 6),
             round(q0 + (q1 - q0) * i / n, 1)] for i in range(n + 1)]


# ------------------------------------------------------- la provenienza


def test_un_percorso_calcolato_non_e_adatto_allo_sci():
    """Il test piu' importante del file. Vedi il commento in cima."""
    assert tracce.ORIGINI["calcolata"]["adatta_a_sci"] is False
    assert tracce.ORIGINI["fonte"]["adatta_a_sci"] is True
    assert tracce.ORIGINI["utente"]["adatta_a_sci"] is True


def test_la_spiegazione_del_calcolato_dice_perche():
    t = tracce.ORIGINI["calcolata"]["spiega"].lower()
    assert "ipotesi" in t
    assert "neve" in t          # dice cosa cambia d'inverno


def test_una_traccia_registrata_batte_quella_della_fonte():
    """Chi c'e' andato ha piu' ragione di un disegno su un sito."""
    assert tracce.sostituisce("fonte", "utente") is True
    assert tracce.sostituisce("calcolata", "fonte") is True
    # e un re-import notturno non cancella la registrazione di una persona
    assert tracce.sostituisce("utente", "fonte") is False
    assert tracce.sostituisce("utente", "calcolata") is False
    assert tracce.sostituisce(None, "calcolata") is True
    # lo stesso tipo si aggiorna (arrivano le quote, la fonte corregge)
    assert tracce.sostituisce("fonte", "fonte") is True


# ------------------------------------------------------ la semplificazione


def test_una_linea_retta_si_riduce_a_due_punti():
    retta = [[44.0 + i * 0.001, 7.0 + i * 0.001] for i in range(50)]
    assert len(tracce.semplifica(retta)) == 2


def test_una_curva_si_tiene_i_punti_che_la_descrivono():
    curva = [[44.0 + 0.01 * math.sin(i / 5), 7.0 + i * 0.001] for i in range(60)]
    ridotta = tracce.semplifica(curva)
    assert 6 < len(ridotta) < len(curva)
    # gli estremi non si perdono mai: sono l'attacco e la cima
    assert ridotta[0] == curva[0] and ridotta[-1] == curva[-1]


def test_la_semplificazione_regge_una_traccia_lunghissima():
    """Iterativa e non ricorsiva: con la ricorsione qui si arrivava al
    limite di python e la scheda moriva."""
    lunga = [[44.0 + i * 0.00001, 7.0 + (i % 7) * 0.00002] for i in range(20000)]
    assert len(tracce.semplifica(lunga)) < 20000


def test_due_punti_restano_due_punti():
    assert len(tracce.semplifica([[44.0, 7.0], [44.1, 7.1]])) == 2
    assert tracce.semplifica([]) == []


# --------------------------------------------------- misure e dislivelli


def test_lo_sviluppo_e_i_dislivelli_tornano():
    p = salita()
    assert 0.5 < tracce.lunghezza_km(p) < 1.5
    su, giu = tracce.dislivelli(p)
    assert 1150 <= su <= 1250        # 1200 m di salita
    assert giu == 0


def test_il_rumore_del_modello_non_diventa_salita():
    """Un profilo campionato oscilla di un paio di metri: sommare quei
    saltini gonfia il dislivello di centinaia di metri sul nulla."""
    piatto = [[44.0 + i * 0.0005, 7.0, 1500 + (2 if i % 2 else -2)]
              for i in range(200)]
    su, giu = tracce.dislivelli(piatto)
    assert su == 0 and giu == 0


def test_la_soglia_non_mangia_la_salita_vera():
    """Il confronto e' con l'ultima quota accettata, non con la precedente:
    una scaletta di gradini da 5 m tutti in salita si conta per intero,
    anche se ogni singolo gradino sta sotto la soglia."""
    scaletta = [[44.0 + i * 0.0005, 7.0, 1500 + i * 5] for i in range(21)]
    su, giu = tracce.dislivelli(scaletta)
    assert 90 <= su <= 100      # 100 m di salita vera
    assert giu == 0


def test_senza_quote_i_dislivelli_sono_zero_non_un_numero_inventato():
    piatto = [[44.0 + i * 0.001, 7.0] for i in range(30)]
    assert tracce.dislivelli(piatto) == (0, 0)
    assert tracce.con_quote(piatto) is False


def test_il_controllo_di_plausibilita_pesca_gli_errori_grossolani():
    """Il caso vero: una gita da 900 m con 4618 m dichiarati."""
    assert tracce.plausibile(4618, 900) is False
    assert tracce.plausibile(1200, 1300) is True
    # e non dice niente quando non puo' dire niente
    assert tracce.plausibile(None, 1200) is None
    assert tracce.plausibile(1200, None) is None


# --------------------------------------------------------------- profilo


def test_il_profilo_si_campiona_a_distanza_costante():
    """Per indice disegnerebbe le curve larghe e i rettilinei stretti: i
    punti di una traccia sono piu' densi dove si gira."""
    p = salita(n=40)
    prof = tracce.profilo(p, passi=20)
    assert len(prof) == 21
    passi = [round(prof[i + 1][0] - prof[i][0], 3) for i in range(len(prof) - 1)]
    assert max(passi) - min(passi) < 0.01     # equidistanti
    assert prof[0][1] < prof[-1][1]           # sale


def test_senza_quote_non_c_e_profilo():
    assert tracce.profilo([[44.0, 7.0], [44.1, 7.1]]) == []


# ------------------------------------------------------------------- GPX


class GitaFinta:
    id = 1
    nome = "Cima delle Saline da Carnino"
    fonte = "camptocamp"
    fonte_url = "https://www.camptocamp.org/routes/123"
    dislivello = 1232


class TracciaFinta:
    origine = "fonte"
    punti = salita(n=20)
    licenza = "CC-BY-SA (camptocamp.org)"
    autori = "Tizio, Caio"
    quote_da = "ors"
    lunghezza_km = 1.0
    dislivello_su = 1200
    dislivello_giu = 0
    caricata_da = None


def test_il_gpx_e_un_gpx_valido():
    xml = tracce.gpx(GitaFinta(), TracciaFinta())
    radice = ET.fromstring(xml)
    assert radice.tag.endswith("gpx")
    punti = [e for e in radice.iter() if e.tag.endswith("trkpt")]
    assert len(punti) == 21
    assert punti[0].get("lat") and punti[0].get("lon")
    quote = [e for e in radice.iter() if e.tag.endswith("ele")]
    assert len(quote) == 21


def test_lattribuzione_viaggia_dentro_il_gpx():
    """Secondo test piu' importante: il file gira, la scheda resta qui."""
    xml = tracce.gpx(GitaFinta(), TracciaFinta())
    assert "CC-BY-SA" in xml
    assert "camptocamp" in xml
    assert "Tizio" in xml
    # e il file dice anche che il bollettino non sta dentro un GPX
    assert "bollettino" in xml.lower()


def test_il_gpx_regge_una_traccia_senza_quote():
    class SenzaQuote(TracciaFinta):
        punti = [[44.0 + i * 0.001, 7.0] for i in range(12)]
    xml = tracce.gpx(GitaFinta(), SenzaQuote())
    radice = ET.fromstring(xml)
    assert not [e for e in radice.iter() if e.tag.endswith("ele")]


def test_il_nome_del_file_si_riconosce():
    assert tracce.nome_file(GitaFinta()).startswith("ndoma-cima-delle-saline")
    assert tracce.nome_file(GitaFinta()).endswith(".gpx")


# ------------------------------------------------ lettura di un GPX caricato


def _gpx_finto(punti, tag: str = "trkpt") -> str:
    dentro = "".join(
        f'<{tag} lat="{p[0]}" lon="{p[1]}">'
        + (f"<ele>{p[2]}</ele>" if len(p) > 2 else "")
        + f"</{tag}>" for p in punti)
    contenitore = "trk><trkseg" if tag == "trkpt" else "rte"
    chiusura = "trkseg></trk" if tag == "trkpt" else "rte"
    return ('<?xml version="1.0"?>'
            '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">'
            f"<{contenitore}>{dentro}</{chiusura}></gpx>")


def test_si_legge_un_gpx_normale():
    punti = tracce.da_gpx(_gpx_finto(salita(n=20)))
    assert len(punti) == 21
    assert punti[0][2] == 1400.0


def test_si_legge_anche_un_itinerario_rtept():
    punti = tracce.da_gpx(_gpx_finto(salita(n=15), tag="rtept"))
    assert len(punti) == 16


def test_un_file_che_non_e_un_gpx_si_rifiuta_con_una_frase_chiara():
    for contenuto in ("", "ciao", "<html><body>no</body></html>"):
        with pytest.raises(tracce.GpxNonValido):
            tracce.da_gpx(contenuto)


def test_due_punti_non_sono_una_traccia():
    with pytest.raises(tracce.GpxNonValido) as e:
        tracce.da_gpx(_gpx_finto([[44.1, 7.1], [44.2, 7.2]]))
    assert "punti" in str(e.value)


def test_una_traccia_fuori_zona_si_rifiuta():
    """Il Cervino non e' nel Cuneese, e l'app copre il Cuneese."""
    lontano = [[45.97 + i * 0.001, 7.66] for i in range(20)]
    with pytest.raises(tracce.GpxNonValido) as e:
        tracce.da_gpx(_gpx_finto(lontano), bbox=(6.55, 44.00, 7.95, 44.75))
    assert "zona" in str(e.value)


def test_la_traccia_deve_partire_o_finire_vicino_alla_gita():
    """Senza questo controllo la traccia del Monviso finisce sulla scheda
    della Meja e non se ne accorge nessuno."""
    p = salita()
    assert tracce.vicina_alla_gita(p, 44.16, 7.79) is True
    assert tracce.vicina_alla_gita(p, 44.60, 7.10) is False


# ------------------------------------------- la geometria di camptocamp


def _mercatore(lat: float, lon: float) -> list:
    return list(camptocamp.wgs84_to_mercator(lon, lat))


def test_la_linea_di_camptocamp_non_si_butta_piu():
    """Prima l'importatore ne prendeva il primo punto e cestinava il resto:
    ogni import passava sopra al dato piu' richiesto."""
    coords = [_mercatore(44.16 + i * 0.001, 7.79 + i * 0.001) for i in range(20)]
    geometry = {"geom_detail": json.dumps({"type": "LineString", "coordinates": coords})}
    punti = camptocamp.linea(geometry)
    assert len(punti) == 20
    assert abs(punti[0][0] - 44.16) < 0.001
    assert abs(punti[0][1] - 7.79) < 0.001


def test_una_multilinea_si_concatena():
    a = [_mercatore(44.16 + i * 0.001, 7.79) for i in range(6)]
    b = [_mercatore(44.17 + i * 0.001, 7.80) for i in range(6)]
    geometry = {"geom_detail": json.dumps({"type": "MultiLineString",
                                           "coordinates": [a, b]})}
    assert len(camptocamp.linea(geometry)) == 12


def test_quando_la_fonte_da_solo_un_punto_non_si_inventa_una_linea():
    geometry = {"geom": json.dumps({"type": "Point",
                                    "coordinates": _mercatore(44.16, 7.79)})}
    assert camptocamp.linea(geometry) == []
    assert camptocamp.linea({}) == []
    assert camptocamp.linea(None) == []


def test_si_preferisce_la_linea_dettagliata_al_punto():
    """`geom` spesso contiene il solo punto e `geom_detail` la linea."""
    coords = [_mercatore(44.16 + i * 0.001, 7.79) for i in range(12)]
    geometry = {
        "geom": json.dumps({"type": "Point", "coordinates": _mercatore(44.16, 7.79)}),
        "geom_detail": json.dumps({"type": "LineString", "coordinates": coords}),
    }
    assert len(camptocamp.linea(geometry)) == 12


# --------------------------------------------------------------------- API


@pytest.fixture()
def mondo():
    Base.metadata.drop_all(engine)
    init_db()
    s = SessionLocal()
    g = Gita(nome="Cima delle Saline", fonte="camptocamp", fonte_id="123",
             fonte_url="https://www.camptocamp.org/routes/123",
             lat=44.16, lon=7.79, dislivello=1232)
    senza = Gita(nome="Punta senza traccia", fonte="camptocamp", fonte_id="456",
                 lat=44.20, lon=7.60)
    s.add_all([g, senza])
    s.commit()
    gid, sid = g.id, senza.id
    tracce.salva(s, g, salita(), "fonte", licenza="CC-BY-SA (camptocamp.org)",
                 autori="Tizio", quote_da="ors")
    s.commit()
    s.close()
    return TestClient(app), gid, sid


def test_la_traccia_si_legge_con_la_sua_provenienza(mondo):
    c, gid, _ = mondo
    d = c.get(f"/api/traccia/{gid}").json()
    assert d["stato"] == "pronta"
    assert d["origine"] == "fonte"
    assert d["adatta_a_sci"] is True
    assert d["con_quote"] is True
    assert d["profilo"] and len(d["profilo"]) > 10
    assert d["dislivello_dichiarato"] == 1232
    assert d["licenza"].startswith("CC-BY-SA")


def test_i_punti_arrivano_semplificati(mondo):
    """In valle si naviga con una tacca: al telefono va la forma della
    linea, non duemila punti."""
    c, gid, _ = mondo
    d = c.get(f"/api/traccia/{gid}").json()
    assert len(d["punti"]) < d["punti_totali"]


def test_quando_la_traccia_non_c_e_lo_si_dice(mondo):
    c, _, sid = mondo
    d = c.get(f"/api/traccia/{sid}").json()
    assert d["stato"] == "assente"
    assert "solo il punto" in d["spiega"]


def test_il_gpx_si_scarica_col_nome_giusto(mondo):
    c, gid, _ = mondo
    r = c.get(f"/api/gpx/{gid}")
    assert r.status_code == 200
    assert "gpx" in r.headers["content-type"]
    assert "attachment" in r.headers["content-disposition"]
    assert "ndoma-cima-delle-saline.gpx" in r.headers["content-disposition"]
    assert "CC-BY-SA" in r.text


def test_senza_traccia_il_gpx_da_404(mondo):
    c, _, sid = mondo
    assert c.get(f"/api/gpx/{sid}").status_code == 404
    assert c.get("/api/gpx/99999").status_code == 404


def test_si_carica_la_propria_traccia_e_prende_il_posto_di_quella_della_fonte(mondo):
    c, gid, _ = mondo
    xml = _gpx_finto(salita(n=30))
    r = c.post(f"/api/traccia/{gid}", headers=intestazione(7001, "Franco"),
               json={"gpx": xml})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["origine"] == "utente"
    assert d["autori"] == "Franco"
    # e ora la scheda mostra quella
    assert c.get(f"/api/traccia/{gid}").json()["origine"] == "utente"


def test_non_si_carica_una_traccia_di_unaltra_montagna(mondo):
    c, _, sid = mondo
    r = c.post(f"/api/traccia/{sid}", headers=intestazione(7002),
               json={"gpx": _gpx_finto(salita())})
    assert r.status_code == 400
    assert "non passa da qui" in r.json()["detail"]


def test_serve_telegram_per_caricare(mondo):
    c, gid, _ = mondo
    assert c.post(f"/api/traccia/{gid}",
                  json={"gpx": _gpx_finto(salita())}).status_code == 401


def test_una_traccia_utente_non_viene_sostituita_da_quella_della_fonte(mondo):
    """Un re-import notturno non deve cancellare la registrazione di una
    persona per rimetterci il disegno del sito."""
    c, gid, _ = mondo
    c.post(f"/api/traccia/{gid}", headers=intestazione(7003),
           json={"gpx": _gpx_finto(salita(n=30))})
    s = SessionLocal()
    g = s.get(Gita, gid)
    t = s.query(Traccia).filter_by(gita_id=gid).one()
    assert tracce.sostituisce(t.origine, "fonte") is False
    s.close()
