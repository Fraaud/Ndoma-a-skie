"""Il ciclo di vita di un passaggio: posti liberi, chiusura, scadenza.

Il buco che questo file chiude: prima l'auto si riempiva in chat e l'uscita
continuava a fare match, quindi il quarto e il quinto scrivevano per un
posto che non c'era piu'; e chi aveva trovato un passaggio continuava a
ricevere match da tre autisti diversi.

Non c'e' nessuna prenotazione, e non e' una mancanza: il perche' sta in cima
a app/passaggi.py.
"""
from __future__ import annotations

import asyncio
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

from app import passaggi  # noqa: E402
from app.db import SessionLocal, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Comune, Gita, Match, Uscita, Utente  # noqa: E402
from app.services import match as match_srv  # noqa: E402

TOKEN = "123456:TESTTOKEN"
SABATO = dt.date.today() + dt.timedelta(days=(5 - dt.date.today().weekday()) % 7 or 7)
CUNEO, BORGO = "004078", "004029"


def intestazione(tg_id: int, nome: str = "Test") -> dict:
    campi = {"auth_date": str(int(time.time())),
             "user": json.dumps({"id": tg_id, "first_name": nome})}
    dcs = "\n".join(f"{k}={campi[k]}" for k in sorted(campi))
    segreto = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    campi["hash"] = hmac.new(segreto, dcs.encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urlencode(campi)}


class FintaUscita:
    def __init__(self, tipo="OFFRO", posti=3, presi=0, stato="aperta",
                 chiusa_perche=None, data=None):
        self.tipo, self.posti, self.presi = tipo, posti, presi
        self.stato, self.chiusa_perche = stato, chiusa_perche
        self.data = data or SABATO
        self.chiusa_il = None


# ------------------------------------------------------------ i conti


def test_i_posti_liberi_sono_offerti_meno_presi():
    assert passaggi.liberi(FintaUscita(posti=3, presi=0)) == 3
    assert passaggi.liberi(FintaUscita(posti=3, presi=2)) == 1
    assert passaggi.liberi(FintaUscita(posti=3, presi=3)) == 0
    # mai negativo, qualunque cosa ci sia in archivio
    assert passaggi.liberi(FintaUscita(posti=2, presi=5)) == 0


def test_la_colonna_nuova_letta_su_una_riga_vecchia_vale_zero():
    """`presi` e' stata aggiunta a un database che esisteva gia': sulle
    righe scritte prima e' NULL, e NULL non e' zero se non lo si dice."""
    vecchia = FintaUscita(posti=3, presi=None)
    assert passaggi.presi(vecchia) == 0
    assert passaggi.liberi(vecchia) == 3


def test_su_una_richiesta_i_posti_liberi_non_vogliono_dire_niente():
    """Chi cerca dichiara di quanti posti ha bisogno, non quanti ne offre."""
    cerco = FintaUscita(tipo="CERCO", posti=1)
    assert passaggi.liberi(cerco) == 0
    assert passaggi.pieno(cerco) is False
    assert passaggi.in_parole(cerco) == "cerca un posto"
    assert passaggi.in_parole(FintaUscita(tipo="CERCO", posti=2)) == "cerca 2 posti"


def test_come_si_leggono_i_posti():
    assert passaggi.in_parole(FintaUscita(posti=3, presi=0)) == "3 posti liberi"
    assert passaggi.in_parole(FintaUscita(posti=3, presi=1)) == "2 di 3 liberi"
    assert passaggi.in_parole(FintaUscita(posti=3, presi=3)) == "auto piena"
    assert passaggi.in_parole(FintaUscita(posti=1, presi=0)) == "1 posto libero"


def test_il_numero_e_assoluto_e_dentro_i_limiti():
    """Assoluto e non un +1: due tocchi rapidi, o uno ripetuto perche' la
    rete e' lenta, con un delta conterebbero due volte."""
    us = FintaUscita(posti=3)
    assert passaggi.imposta_presi(us, 2) == 1
    assert passaggi.imposta_presi(us, 2) == 1        # idempotente
    assert passaggi.imposta_presi(us, 99) == 0 and us.presi == 3
    assert passaggi.imposta_presi(us, -4) == 3 and us.presi == 0
    with pytest.raises(ValueError):
        passaggi.imposta_presi(FintaUscita(tipo="CERCO"), 1)


def test_un_autista_non_trova_un_passaggio_e_un_passeggero_non_riempie_lauto():
    assert passaggi.motivo_ammesso(FintaUscita(tipo="OFFRO"), "pieno") is True
    assert passaggi.motivo_ammesso(FintaUscita(tipo="OFFRO"), "sistemato") is False
    assert passaggi.motivo_ammesso(FintaUscita(tipo="CERCO"), "sistemato") is True
    assert passaggi.motivo_ammesso(FintaUscita(tipo="CERCO"), "pieno") is False
    # "scaduta" non la sceglie nessuno: la mette il lavoro notturno
    assert passaggi.motivo_ammesso(FintaUscita(tipo="OFFRO"), "scaduta") is False


def test_una_chiusura_a_cose_fatte_non_avvisa_nessuno():
    class FintoAutore:
        nome = "Marco"
    us = FintaUscita()
    passaggi.chiudi(us, "scaduta")
    assert passaggi.testo_chiusura(us, FintoAutore(), "Cima delle Saline") == ""
    passaggi.chiudi(us, "pieno")
    testo = passaggi.testo_chiusura(us, FintoAutore(), "Cima delle Saline")
    assert "Marco" in testo and "Cima delle Saline" in testo


# --------------------------------------------------------------- l'archivio


@pytest.fixture()
def mondo():
    Base.metadata.drop_all(engine)
    init_db()
    s = SessionLocal()
    s.add_all([
        Comune(istat=CUNEO, nome="Cuneo", provincia="Cuneo", lat=44.39, lon=7.55),
        Comune(istat=BORGO, nome="Borgo San Dalmazzo", provincia="Cuneo",
               lat=44.33, lon=7.49),
    ])
    g = Gita(nome="Testa Malacosta", fonte="test", fonte_id="1",
             lat=44.32, lon=7.03, valle="Valle Stura", istat=CUNEO)
    s.add(g)
    s.commit()
    gid = g.id
    s.close()
    return TestClient(app), gid


def _pubblica(c, tg_id, tipo, gid, posti, nome="Tizio", istat=CUNEO):
    return c.post("/api/uscite", headers=intestazione(tg_id, nome), json={
        "tipo": tipo, "gita_id": gid, "data": SABATO.isoformat(),
        "posti": posti, "istat_partenza": istat,
    }).json()


def test_chi_guida_scala_i_posti_e_a_zero_luscita_si_chiude(mondo):
    """Il controllo che mancava."""
    c, gid = mondo
    offro = _pubblica(c, 9001, "OFFRO", gid, 2, "Marco")
    assert offro["posti_liberi"] == 2 and offro["posti_testo"] == "2 posti liberi"

    d = c.post(f"/api/uscite/{offro['id']}/posti", headers=intestazione(9001),
               json={"presi": 1}).json()
    assert d["posti_liberi"] == 1 and d["chiusa"] is False
    assert d["stato"] == "aperta"
    assert d["posti_testo"] == "1 di 2 liberi"

    d = c.post(f"/api/uscite/{offro['id']}/posti", headers=intestazione(9001),
               json={"presi": 2}).json()
    assert d["posti_liberi"] == 0
    assert d["chiusa"] is True
    assert d["stato"] == "chiusa"
    assert d["chiusa_perche"] == "pieno"
    assert d["chiusa_etichetta"] == "auto piena"


def test_unauto_piena_non_fa_piu_match(mondo):
    """Senza questo il quarto e il quinto scrivono per un posto che non c'e'."""
    c, gid = mondo
    offro = _pubblica(c, 9002, "OFFRO", gid, 1, "Marco")
    c.post(f"/api/uscite/{offro['id']}/posti", headers=intestazione(9002),
           json={"presi": 1})

    s = SessionLocal()
    a = s.get(Uscita, offro["id"])
    # anche prima della chiusura, la regola guarda i posti LIBERI
    a.stato = "aperta"
    s.commit()
    cerco = _pubblica(c, 9003, "CERCO", gid, 1, "Chiara", istat=BORGO)
    b = s.get(Uscita, cerco["id"])
    esito = match_srv.spiega(s, a, b)
    assert esito["scarto"] and "posti liberi" in esito["scarto"]
    s.close()


def test_il_pulsante_auto_piena_chiude_in_un_tocco(mondo):
    c, gid = mondo
    offro = _pubblica(c, 9004, "OFFRO", gid, 4, "Marco")
    d = c.post(f"/api/uscite/{offro['id']}/posti", headers=intestazione(9004),
               json={"presi": 4}).json()
    assert d["chiusa"] is True and d["pieno"] is True


def test_si_puo_tornare_indietro_se_uno_da_forfait(mondo):
    c, gid = mondo
    offro = _pubblica(c, 9005, "OFFRO", gid, 3, "Marco")
    c.post(f"/api/uscite/{offro['id']}/posti", headers=intestazione(9005),
           json={"presi": 2})
    d = c.post(f"/api/uscite/{offro['id']}/posti", headers=intestazione(9005),
               json={"presi": 1}).json()
    assert d["posti_liberi"] == 2 and d["stato"] == "aperta"


def test_i_posti_li_tiene_solo_chi_offre_e_solo_sulla_sua_uscita(mondo):
    c, gid = mondo
    offro = _pubblica(c, 9006, "OFFRO", gid, 3, "Marco")
    cerco = _pubblica(c, 9007, "CERCO", gid, 1, "Chiara", istat=BORGO)
    # un altro utente non tocca la mia uscita
    assert c.post(f"/api/uscite/{offro['id']}/posti", headers=intestazione(9007),
                  json={"presi": 3}).status_code == 403
    # e su una richiesta non ha senso
    assert c.post(f"/api/uscite/{cerco['id']}/posti", headers=intestazione(9007),
                  json={"presi": 1}).status_code == 400


def test_su_unuscita_gia_chiusa_non_si_scala_niente(mondo):
    c, gid = mondo
    offro = _pubblica(c, 9008, "OFFRO", gid, 2, "Marco")
    c.post(f"/api/uscite/{offro['id']}/chiudi", headers=intestazione(9008),
           json={"motivo": "annullata"})
    assert c.post(f"/api/uscite/{offro['id']}/posti", headers=intestazione(9008),
                  json={"presi": 1}).status_code == 409


def test_chi_cerca_dice_sistemato_e_la_sua_richiesta_si_chiude(mondo):
    """Senza questo tre autisti diversi insistono con uno che ha risolto."""
    c, gid = mondo
    cerco = _pubblica(c, 9009, "CERCO", gid, 1, "Chiara", istat=BORGO)
    d = c.post(f"/api/uscite/{cerco['id']}/chiudi", headers=intestazione(9009),
               json={"motivo": "sistemato"}).json()
    assert d["motivo"] == "sistemato"
    mie = c.get("/api/mie", headers=intestazione(9009)).json()
    assert mie[0]["stato"] == "chiusa"
    assert mie[0]["chiusa_etichetta"] == "ha trovato un passaggio"


def test_un_motivo_che_non_sta_in_piedi_si_rifiuta(mondo):
    c, gid = mondo
    offro = _pubblica(c, 9010, "OFFRO", gid, 2, "Marco")
    r = c.post(f"/api/uscite/{offro['id']}/chiudi", headers=intestazione(9010),
               json={"motivo": "sistemato"})
    assert r.status_code == 400
    assert "non si chiude" in r.json()["detail"]


def test_chiudere_senza_motivo_vale_annullata(mondo):
    """Era quello che faceva il vecchio pulsante: non deve cambiare."""
    c, gid = mondo
    offro = _pubblica(c, 9011, "OFFRO", gid, 2, "Marco")
    d = c.post(f"/api/uscite/{offro['id']}/chiudi",
               headers=intestazione(9011)).json()
    assert d["motivo"] == "annullata"


def test_chi_va_avvisato_di_una_chiusura_e_chi_aveva_un_match(mondo):
    c, gid = mondo
    offro = _pubblica(c, 9012, "OFFRO", gid, 2, "Marco")
    cerco = _pubblica(c, 9013, "CERCO", gid, 1, "Chiara", istat=BORGO)

    s = SessionLocal()
    # il match lo ha già scritto la pubblicazione, in sottofondo
    assert s.query(Match).count() == 1
    a, b = s.get(Uscita, offro["id"]), s.get(Uscita, cerco["id"])

    assert [x.id for x in passaggi.controparti(s, a)] == [b.id]
    assert [x.id for x in passaggi.controparti(s, b)] == [a.id]

    # una controparte che ha gia' chiuso non si avvisa: non le serve
    passaggi.chiudi(b, "sistemato")
    s.commit()
    assert passaggi.controparti(s, a) == []
    s.close()


# ---------------------------------------------------------------- scadenza


def test_le_uscite_passate_si_chiudono_da_sole(mondo):
    """Restavano "aperta" per sempre: invisibili nell'elenco, ma vive nel
    profilo di chi le aveva pubblicate."""
    c, gid = mondo
    s = SessionLocal()
    u = Utente(tg_id=9014, nome="Vecchio")
    s.add(u)
    s.commit()
    s.add_all([
        Uscita(autore_id=u.id, gita_id=gid, tipo="OFFRO", posti=3,
               data=dt.date.today() - dt.timedelta(days=3)),
        Uscita(autore_id=u.id, gita_id=gid, tipo="OFFRO", posti=3,
               data=dt.date.today() + dt.timedelta(days=3)),
    ])
    s.commit()

    assert passaggi.chiudi_scadute(s) == 1
    stati = {(x.data > dt.date.today()): (x.stato, x.chiusa_perche)
             for x in s.query(Uscita).all()}
    assert stati[False] == ("chiusa", "scaduta")
    assert stati[True][0] == "aperta"
    # e rilanciarlo non fa danni
    assert passaggi.chiudi_scadute(s) == 0
    s.close()


def test_la_chiusura_delle_scadute_gira_anche_con_la_simulazione_accesa(monkeypatch):
    """Se stesse dopo il `return` del ramo simulazione non girerebbe mai, e
    la simulazione resta accesa per mesi."""
    from app import aggiornamento, simulazione

    Base.metadata.drop_all(engine)
    init_db()
    s = SessionLocal()
    u = Utente(tg_id=9015, nome="Vecchio")
    g = Gita(nome="X", fonte="test", fonte_id="x", lat=44.3, lon=7.1)
    s.add_all([u, g])
    s.commit()
    s.add(Uscita(autore_id=u.id, gita_id=g.id, tipo="OFFRO", posti=2,
                 data=dt.date.today() - dt.timedelta(days=2)))
    s.commit()

    monkeypatch.setenv("SIMULAZIONE_INVERNO", "2026-02-14")
    monkeypatch.setattr(simulazione, "attiva", lambda: True)

    async def finta_carica(db, **kw):
        return {"simulazione": True}

    monkeypatch.setattr(aggiornamento.simulazione, "carica", finta_carica)
    asyncio.run(aggiornamento.aggiorna_tutto(s, verboso=False))

    passata = s.query(Uscita).one()
    assert passata.stato == "chiusa" and passata.chiusa_perche == "scaduta"
    s.close()
