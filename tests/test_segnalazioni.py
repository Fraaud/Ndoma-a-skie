"""Le condizioni raccontate da chi c'e' stato.

Il test che conta di piu' e' `test_nessuna_etichetta_da_giudizi`: le
etichette raccontano cosa si e' visto, non se si poteva andare. Se un
giorno viene la tentazione di aggiungere "condizioni ottime" o "tranquilla,
si va", e' quel test che si mette a protestare - ed e' il suo lavoro.
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

from app import segnalazioni as sg  # noqa: E402
from app.db import SessionLocal, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Gita, Segnalazione  # noqa: E402

TOKEN = "123456:TESTTOKEN"
OGGI = dt.date.today()
IERI = (OGGI - dt.timedelta(days=1)).isoformat()


def intestazione(tg_id: int, nome: str = "Test") -> dict:
    campi = {"auth_date": str(int(time.time())),
             "user": json.dumps({"id": tg_id, "first_name": nome})}
    dcs = "\n".join(f"{k}={campi[k]}" for k in sorted(campi))
    segreto = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    campi["hash"] = hmac.new(segreto, dcs.encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urlencode(campi)}


@pytest.fixture()
def gita_e_client():
    Base.metadata.drop_all(engine)
    init_db()
    s = SessionLocal()
    g = Gita(nome="Cima delle Saline", fonte="test", fonte_id="1", lat=44.16, lon=7.79)
    s.add(g)
    s.commit()
    gid = g.id
    s.close()
    return TestClient(app), gid


# --------------------------------------------------------- il vocabolario


def test_nessuna_etichetta_da_giudizi():
    """Nessuna etichetta dice se si poteva andare. E' il punto di tutto.

    Il giudizio lo da' il bollettino, e poi lo da' chi guarda il pendio.
    Un'etichetta come "era sicuro" trasformerebbe una segnalazione in un
    consiglio, e un consiglio in questo posto e' pericoloso: fa partire
    qualcuno senza leggere il bollettino.
    """
    tutte = {**sg.NEVE, **sg.TRACCIA, **sg.ACCESSO}
    for chiave, testo in tutte.items():
        for parola in sg.PAROLE_DI_GIUDIZIO:
            assert parola not in testo.lower(), \
                f"l'etichetta «{testo}» ({chiave}) contiene «{parola}»: e' un giudizio"


def test_l_avvertenza_dice_a_chi_scrive_qual_e_il_confine():
    # non basta che il codice sia corretto: chi compila il modulo deve
    # leggere perche' non trova l'etichetta che si aspettava
    t = sg.VOCABOLARIO["avvertenza"].lower()
    assert "cosa hai visto" in t
    assert "bollettino" in t


# ---------------------------------------------------------------- pulisci


def test_le_etichette_inventate_restano_fuori():
    p = sg.pulisci({"neve": ["polvere", "era_sicuro", "polvere"],
                    "traccia": "ottima", "accesso": ["strada_aperta", "boh"]})
    assert p["neve"] == ["polvere"]          # niente doppioni, niente inventate
    assert p["traccia"] is None
    assert p["accesso"] == ["strada_aperta"]


def test_piu_di_tre_etichette_sulla_neve_non_descrivono_niente():
    p = sg.pulisci({"neve": list(sg.NEVE)})
    assert len(p["neve"]) == sg.MAX_NEVE


def test_una_quota_impossibile_vale_come_non_detta():
    assert sg.pulisci({"quota_cambio": 9000})["quota_cambio"] is None
    assert sg.pulisci({"quota_cambio": "duemila"})["quota_cambio"] is None
    assert sg.pulisci({"quota_cambio": 2100})["quota_cambio"] == 2100


def test_la_nota_si_taglia_e_lo_spazio_vuoto_vale_null():
    assert sg.pulisci({"nota": "   "})["nota"] is None
    assert len(sg.pulisci({"nota": "x" * 500})["nota"]) == sg.MAX_NOTA


def test_una_segnalazione_senza_niente_e_vuota():
    assert sg.vuota(sg.pulisci({})) is True
    assert sg.vuota(sg.pulisci({"traccia": "battuta"})) is False
    assert sg.vuota(sg.pulisci({"nota": "ghiaccio nel canale"})) is False


def test_la_quota_e_un_etichetta_a_se():
    """Non si attacca a una delle etichette della neve.

    "crosta portante fino a 2100 m" direbbe una cosa che l'utente non ha
    dichiarato: l'ordine delle pillole toccate non e' l'ordine delle quote.
    """
    class Finta:
        neve = ["polvere", "crosta_portante"]
        traccia = "battuta"
        accesso = ["strada_chiusa"]
        quota_cambio = 2100
    e = sg.etichette(Finta())
    assert "polvere" in e and "crosta portante" in e
    assert "cambiava verso i 2100 m" in e
    assert not any("fino a 2100" in x for x in e)
    assert "traccia battuta" in e and "strada chiusa prima" in e


def test_quanto_e_vecchia_si_dice_in_parole():
    assert sg.quando(0) == "oggi"
    assert sg.quando(1) == "ieri"
    assert sg.quando(3) == "3 giorni fa"
    assert "settimana" in sg.quando(9)


# -------------------------------------------------------------------- API


def test_si_racconta_e_si_rilegge(gita_e_client):
    c, gid = gita_e_client
    r = c.post("/api/segnalazioni", headers=intestazione(5001, "Franco"), json={
        "gita_id": gid, "giorno": IERI,
        "neve": ["crosta_portante"], "traccia": "battuta",
        "accesso": ["strada_aperta"], "quota_cambio": 2100,
        "nota": "sotto i 1700 si camminava",
    })
    assert r.status_code == 200, r.text

    d = c.get(f"/api/segnalazioni/{gid}").json()
    assert len(d["segnalazioni"]) == 1
    s = d["segnalazioni"][0]
    assert s["quando"] == "ieri" and s["fresca"] is True
    assert "crosta portante" in s["etichette"]
    assert "cambiava verso i 2100 m" in s["etichette"]
    assert s["autore"]["nome"] == "Franco"
    # chi guarda da fuori Telegram non e' nessuno: nessuna e' "sua"
    assert s["mia"] is False


def test_chi_guarda_da_telegram_riconosce_le_proprie(gita_e_client):
    c, gid = gita_e_client
    c.post("/api/segnalazioni", headers=intestazione(5002),
           json={"gita_id": gid, "giorno": IERI, "traccia": "battuta"})
    mie = c.get(f"/api/segnalazioni/{gid}", headers=intestazione(5002)).json()
    altri = c.get(f"/api/segnalazioni/{gid}", headers=intestazione(5003)).json()
    assert mie["segnalazioni"][0]["mia"] is True
    assert altri["segnalazioni"][0]["mia"] is False


def test_lo_stesso_giorno_si_corregge_invece_di_duplicare(gita_e_client):
    c, gid = gita_e_client
    c.post("/api/segnalazioni", headers=intestazione(5004),
           json={"gita_id": gid, "giorno": IERI, "neve": ["polvere"]})
    r = c.post("/api/segnalazioni", headers=intestazione(5004),
               json={"gita_id": gid, "giorno": IERI, "neve": ["umida"]})
    assert r.json()["aggiornata"] is True
    d = c.get(f"/api/segnalazioni/{gid}").json()["segnalazioni"]
    assert len(d) == 1 and d[0]["neve"] == ["umida"]


def test_una_segnalazione_vuota_non_si_salva(gita_e_client):
    """Meglio nessuna riga che una riga che non dice niente."""
    c, gid = gita_e_client
    r = c.post("/api/segnalazioni", headers=intestazione(5005),
               json={"gita_id": gid, "giorno": IERI, "neve": ["inventata"]})
    assert r.status_code == 400
    assert c.get(f"/api/segnalazioni/{gid}").json()["segnalazioni"] == []


def test_non_si_racconta_un_giorno_che_non_c_e_ancora_stato(gita_e_client):
    c, gid = gita_e_client
    domani = (OGGI + dt.timedelta(days=1)).isoformat()
    r = c.post("/api/segnalazioni", headers=intestazione(5006),
               json={"gita_id": gid, "giorno": domani, "traccia": "battuta"})
    assert r.status_code == 400


def test_troppo_tempo_fa_non_si_accetta(gita_e_client):
    c, gid = gita_e_client
    vecchio = (OGGI - dt.timedelta(days=sg.GIORNI_VALIDI + 5)).isoformat()
    r = c.post("/api/segnalazioni", headers=intestazione(5007),
               json={"gita_id": gid, "giorno": vecchio, "traccia": "battuta"})
    assert r.status_code == 400


def test_le_vecchie_sparisco_dall_elenco(gita_e_client):
    """La neve di un mese fa non e' un'informazione su questo weekend."""
    c, gid = gita_e_client
    s = SessionLocal()
    from app.models import Utente
    u = Utente(tg_id=5008, nome="Vecchio")
    s.add(u)
    s.commit()
    s.add(Segnalazione(utente_id=u.id, gita_id=gid,
                       giorno=OGGI - dt.timedelta(days=sg.GIORNI_VALIDI + 1),
                       neve=["polvere"], accesso=[]))
    s.commit()
    s.close()
    assert c.get(f"/api/segnalazioni/{gid}").json()["segnalazioni"] == []


def test_una_segnalazione_non_fresca_e_marcata(gita_e_client):
    c, gid = gita_e_client
    s = SessionLocal()
    from app.models import Utente
    u = Utente(tg_id=5009, nome="Tempo")
    s.add(u)
    s.commit()
    s.add(Segnalazione(utente_id=u.id, gita_id=gid,
                       giorno=OGGI - dt.timedelta(days=sg.GIORNI_FRESCA + 3),
                       neve=["polvere"], accesso=[]))
    s.commit()
    s.close()
    d = c.get(f"/api/segnalazioni/{gid}").json()["segnalazioni"][0]
    assert d["fresca"] is False


def test_non_si_cancella_la_segnalazione_di_un_altro(gita_e_client):
    c, gid = gita_e_client
    sid = c.post("/api/segnalazioni", headers=intestazione(5010),
                 json={"gita_id": gid, "giorno": IERI,
                       "traccia": "battuta"}).json()["id"]
    assert c.delete(f"/api/segnalazioni/{sid}", headers=intestazione(5011)).status_code == 404
    assert c.delete(f"/api/segnalazioni/{sid}", headers=intestazione(5010)).status_code == 200


def test_serve_telegram_per_scrivere_ma_non_per_leggere(gita_e_client):
    c, gid = gita_e_client
    assert c.post("/api/segnalazioni",
                  json={"gita_id": gid, "giorno": IERI, "traccia": "battuta"}
                  ).status_code == 401
    assert c.get(f"/api/segnalazioni/{gid}").status_code == 200


def test_una_gita_che_non_esiste_da_404(gita_e_client):
    c, _ = gita_e_client
    r = c.post("/api/segnalazioni", headers=intestazione(5012),
               json={"gita_id": 99999, "giorno": IERI, "traccia": "battuta"})
    assert r.status_code == 404


def test_il_vocabolario_viaggia_con_l_elenco(gita_e_client):
    """Il client non scrive nessuna etichetta a mano: le riceve da qui."""
    c, gid = gita_e_client
    voc = c.get(f"/api/segnalazioni/{gid}").json()["vocabolario"]
    assert set(voc["neve"]) == set(sg.NEVE)
    assert voc["max_nota"] == sg.MAX_NOTA
    assert voc["giorni_validi"] == sg.GIORNI_VALIDI
