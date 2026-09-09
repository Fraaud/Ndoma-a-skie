"""Dati finti per provare l'interfaccia SENZA rete.

ATTENZIONE: le coordinate qui dentro sono approssimative e servono solo a far
vedere come si presenta l'app. NON sono dati da usare in montagna e non vanno
lasciati nel database vero: appena `scripts/importa.py` funziona, cancella
data/ndoma.db e riparti dalle fonti vere.

  python scripts/seed_demo.py
"""
from __future__ import annotations

import datetime as dt
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import init_db, session_scope  # noqa: E402
from app.models import CacheBollettino, CacheMeteo, Comune, Gita, Uscita, Utente  # noqa: E402

COMUNI = [
    ("004078", "Cuneo", 44.39, 7.55),
    ("004029", "Borgo San Dalmazzo", 44.33, 7.49),
    ("004083", "Demonte", 44.31, 7.30),
    ("004175", "Pietraporzio", 44.32, 7.03),
    ("004236", "Vernante", 44.24, 7.53),
    ("004087", "Entracque", 44.24, 7.40),
    ("004203", "Saluzzo", 44.64, 7.49),
    ("004006", "Argentera", 44.39, 6.94),
]

GITE = [
    # nome, lat, lon, q_min, q_max, disl, esposizione, difficolta, valle
    ("Testa Malacosta da Pontebernardo", 44.34, 7.02, 1310, 2854, 1550, "N,NE", "BSA", "Valle Stura"),
    ("Monte Bersaio da Pietraporzio", 44.31, 7.05, 1250, 2410, 1160, "E,SE", "MS", "Valle Stura"),
    ("Rocca La Meja da Preit", 44.42, 6.99, 1760, 2831, 1080, "N,NO", "BSA", "Valle Maira"),
    ("Cima Pian Ballaur da Carnino", 44.15, 7.72, 1390, 2604, 1220, "N", "BSA", "Valle Tanaro"),
    ("Monte Matto dal Gias delle Mosche", 44.22, 7.31, 1750, 3097, 1350, "N,NE", "OSA", "Valle Gesso"),
    ("Punta Colombo da Sant'Anna", 44.20, 7.44, 1780, 2400, 640, "E", "MS", "Valle Gesso"),
    ("Cime de Vermeil dal Colle della Lombarda", 44.21, 7.13, 1970, 2760, 830, "NE", "BS", "Mercantour"),
]


def _serie_meteo(neve_recente_cm: float, vento: float, temp: float,
                 riferimento: dt.date | None = None) -> dict:
    """Serie oraria sintetica coerente con quello che restituisce Open-Meteo.

    La nevicata viene messa fra le 40 e le 20 ore prima delle 8 del mattino
    del giorno di riferimento (di norma il sabato), cosi' la vista Weekend
    mostra qualcosa di sensato."""
    riferimento = riferimento or dt.date.today()
    inizio = dt.datetime.combine(dt.date.today(), dt.time(0, 0)) - dt.timedelta(days=4)
    partenza = dt.datetime.combine(riferimento, dt.time(8, 0))
    tempi, neve, vento_s, temp_s, pioggia, quota0, profondita = [], [], [], [], [], [], []
    ore = 24 * 10
    for i in range(ore):
        t = inizio + dt.timedelta(hours=i)
        tempi.append(t.strftime("%Y-%m-%dT%H:00"))
        ore_fa = (partenza - t).total_seconds() / 3600
        cade = 20 <= ore_fa <= 40
        neve.append(round(neve_recente_cm / 20.0, 2) if cade else 0.0)
        pioggia.append(0.0)
        vento_s.append(round(vento * (1.3 if cade else 1.0) * random.uniform(0.8, 1.2), 1))
        temp_s.append(round(temp + math.sin(i / 12) * 3, 1))
        quota0.append(1100 + int(math.sin(i / 30) * 400))
        profondita.append(0.6)
    giorni, tmin, tmax, neve_g = [], [], [], []
    for g in range(10):
        d = (inizio + dt.timedelta(days=g)).date()
        giorni.append(d.isoformat())
        tmin.append(round(temp - 4, 1))
        tmax.append(round(temp + 4, 1))
        neve_g.append(round(sum(neve[g * 24:(g + 1) * 24]), 1))
    return {
        "hourly": {
            "time": tempi, "snowfall": neve, "rain": pioggia,
            "wind_speed_10m": vento_s, "wind_gusts_10m": [v * 1.6 for v in vento_s],
            "wind_direction_10m": [280] * ore, "temperature_2m": temp_s,
            "freezing_level_height": quota0, "snow_depth": profondita,
        },
        "daily": {"time": giorni, "temperature_2m_min": tmin, "temperature_2m_max": tmax,
                  "snowfall_sum": neve_g, "precipitation_sum": [x * 0.8 for x in neve_g]},
    }


BOLLETTINO_DEMO = {
    "regioni": ["IT-21-DEMO"],
    "grado_massimo": 3,
    "gradi": [{"grado": 3, "testo": "Marcato", "periodo": None,
               "quota_min": 2200, "quota_max": None}],
    "problemi": [
        {"tipo": "wind_slab", "tipo_it": "Lastroni da vento",
         "esposizioni": ["N", "NE", "E"], "quota_min": 2200, "quota_max": None,
         "periodo": None},
        {"tipo": "new_snow", "tipo_it": "Neve fresca",
         "esposizioni": [], "quota_min": 1800, "quota_max": None, "periodo": None},
    ],
    "sintesi": "[DATI DIMOSTRATIVI] Accumuli da vento nelle conche e dietro i dossi "
               "alle quote superiori. Distacchi provocabili gia' con debole sovraccarico.",
    "emesso_il": dt.datetime.now().isoformat(timespec="minutes"),
    "ente": "ESEMPIO - non e' un bollettino reale",
    "fonte_url": None,
}


def main() -> None:
    init_db()
    random.seed(7)
    sabato = dt.date.today() + dt.timedelta(days=(5 - dt.date.today().weekday()) % 7)
    with session_scope() as db:
        for istat, nome, lat, lon in COMUNI:
            if not db.get(Comune, istat):
                db.add(Comune(istat=istat, nome=nome, provincia="Cuneo", lat=lat, lon=lon))

        condizioni = [(55, 12, -9), (40, 30, -6), (25, 55, -4), (12, 15, -2),
                      (60, 10, -11), (5, 20, 1), (35, 25, -7)]
        for i, (nome, lat, lon, qmin, qmax, disl, esp, dif, valle) in enumerate(GITE):
            g = db.query(Gita).filter_by(fonte="demo", fonte_id=str(i)).one_or_none()
            if not g:
                g = Gita(
                    nome=nome, fonte="demo", fonte_id=str(i),
                    fonte_url="https://www.camptocamp.org/routes",
                    licenza="dati dimostrativi", lat=lat, lon=lon,
                    quota_min=qmin, quota_max=qmax, dislivello=disl,
                    esposizione=esp, difficolta=dif, valle=valle,
                    comune=COMUNI[i % len(COMUNI)][1],
                    istat=COMUNI[i % len(COMUNI)][0],
                    eaws_region="IT-21-DEMO", verificata=False,
                )
                db.add(g)
                db.flush()
            neve, vento, temp = condizioni[i % len(condizioni)]
            if not db.query(CacheMeteo).filter_by(gita_id=g.id, giorno=dt.date.today()).first():
                db.add(CacheMeteo(gita_id=g.id, giorno=dt.date.today(),
                                  payload=_serie_meteo(neve, vento, temp, sabato)))

        if not db.query(CacheBollettino).filter_by(eaws_region="IT-21-DEMO",
                                                   giorno=dt.date.today()).first():
            db.add(CacheBollettino(eaws_region="IT-21-DEMO", giorno=dt.date.today(),
                                   payload=BOLLETTINO_DEMO))

        for tg_id, username, nome, istat in [
            (900001, "marco_demo", "Marco", "004078"),
            (900002, "giulia_demo", "Giulia", "004029"),
            (900003, "pietro_demo", "Pietro", "004203"),
        ]:
            if not db.query(Utente).filter_by(tg_id=tg_id).first():
                c = db.get(Comune, istat)
                db.add(Utente(tg_id=tg_id, username=username, nome=nome,
                              istat_partenza=istat, comune_partenza=c.nome,
                              lat_partenza=c.lat, lon_partenza=c.lon,
                              ha_auto=tg_id != 900003, posti_default=3))
        db.flush()

        gite = db.query(Gita).filter_by(fonte="demo").all()
        utenti = db.query(Utente).filter(Utente.tg_id > 900000).all()
        if not db.query(Uscita).first() and gite and utenti:
            db.add(Uscita(autore_id=utenti[0].id, gita_id=gite[0].id, tipo="OFFRO",
                          data=sabato, posti=3, ora_partenza="05:30",
                          istat_partenza="004078", comune_partenza="Cuneo",
                          lat_partenza=44.39, lon_partenza=7.55,
                          note="Rientro entro le 17, ho il portasci sul tetto"))
            db.add(Uscita(autore_id=utenti[1].id, gita_id=gite[0].id, tipo="CERCO",
                          data=sabato, posti=1, ora_partenza="05:30",
                          istat_partenza="004029", comune_partenza="Borgo San Dalmazzo"))
            db.add(Uscita(autore_id=utenti[2].id, gita_id=gite[4].id, tipo="COMPAGNI",
                          data=sabato + dt.timedelta(days=1), posti=1, flessibilita=1,
                          istat_partenza="004203", comune_partenza="Saluzzo",
                          note="Prima volta sul Matto, cerco qualcuno che lo conosce"))

    print("Dati dimostrativi inseriti. Ricorda: NON sono dati reali.")
    print("Avvia:  uvicorn app.main:app --reload")


if __name__ == "__main__":
    main()
