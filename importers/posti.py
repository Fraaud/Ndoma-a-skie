"""Parcheggi, ripari e piole da OpenStreetMap via Overpass (ODbL).

Tre interrogazioni separate e non una sola: se Overpass va in timeout su
quella dei ristoranti - la piu' grossa - i parcheggi restano comunque
importati. Una query unica avrebbe fatto perdere tutto insieme.

Sui parcheggi c'e' un filtro che vale la pena spiegare: nel bbox ci sono
tutti i parcheggi di Cuneo, Mondovi' e Saluzzo, che non sono attacchi di
gite. Si tiene solo quello che sta entro pochi chilometri da una gita del
catalogo. Il conto si fa con una griglia di celle da ~2 km, non confrontando
ogni parcheggio con ogni gita: il secondo modo sarebbe un milione di radici
quadrate per un dato che si aggiorna una volta al mese.

Sulle piole il filtro e' diverso: si tengono tutte quelle con un nome nei
comuni che conosciamo, perche' la piola giusta non e' vicino all'attacco -
e' in fondovalle, sulla strada di casa. Chi cerca sceglie poi lungo il
corridoio del ritorno (vedi app/posti.py).
"""
from __future__ import annotations

import asyncio
import math
import sys

import httpx

from app import posti as dominio
from app.config import settings
from app.db import session_scope
from app.geo import comune_di, distanza_km
from app.models import Gita, Posto

# ~2 km di lato: la cella e' solo un raccoglitore, la distanza vera si
# calcola dopo sui pochi candidati della cella e delle otto intorno.
LATO_CELLA = 0.02

# I ripari servono in Emergenza, quindi si prendono piu' larghi dei
# parcheggi: mezz'ora di cammino sono un paio di chilometri, ma sapere che
# a otto c'e' un rifugio e' comunque meglio che non saperlo.
RAGGIO_RIPARI_DA_GITA = 8.0

QUERY = {
    "parcheggi": """
[out:json][timeout:180];
(
  node["amenity"="parking"]({sud},{ovest},{nord},{est});
  way["amenity"="parking"]({sud},{ovest},{nord},{est});
);
out center tags;
""",
    "ripari": """
[out:json][timeout:180];
(
  node["tourism"~"^(alpine_hut|wilderness_hut)$"]({sud},{ovest},{nord},{est});
  way["tourism"~"^(alpine_hut|wilderness_hut)$"]({sud},{ovest},{nord},{est});
  node["amenity"="shelter"]({sud},{ovest},{nord},{est});
);
out center tags;
""",
    "piole": """
[out:json][timeout:180];
(
  node["amenity"~"^(restaurant|bar|pub|cafe)$"]["name"]({sud},{ovest},{nord},{est});
  way["amenity"~"^(restaurant|bar|pub|cafe)$"]["name"]({sud},{ovest},{nord},{est});
);
out center tags;
""",
}


def _cella(lat: float, lon: float) -> tuple[int, int]:
    return int(math.floor(lat / LATO_CELLA)), int(math.floor(lon / LATO_CELLA))


def griglia_gite(db) -> dict:
    """Le gite raccolte per cella, per rispondere in fretta a "e' vicino?"."""
    g: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for lat, lon in db.query(Gita.lat, Gita.lon).filter(Gita.attiva.is_(True)).all():
        g.setdefault(_cella(lat, lon), []).append((lat, lon))
    return g


def vicino_a_una_gita(lat: float, lon: float, griglia: dict, entro_km: float) -> bool:
    """Guarda la cella e le otto intorno: oltre non ci puo' essere niente
    piu' vicino di `entro_km`, finche' il raggio resta sotto il lato."""
    ci, cj = _cella(lat, lon)
    passi = max(1, int(math.ceil(entro_km / (LATO_CELLA * 111.0))))
    for i in range(ci - passi, ci + passi + 1):
        for j in range(cj - passi, cj + passi + 1):
            for glat, glon in griglia.get((i, j), ()):
                if distanza_km(lat, lon, glat, glon) <= entro_km:
                    return True
    return False


async def _scarica(client: httpx.AsyncClient, nome: str) -> list[dict]:
    q = QUERY[nome].format(
        ovest=settings.bbox[0], sud=settings.bbox[1],
        est=settings.bbox[2], nord=settings.bbox[3],
    )
    try:
        r = await client.post(settings.url_overpass, data={"data": q})
    except Exception as e:
        print(f"  {nome}: Overpass non raggiungibile ({e})", file=sys.stderr)
        return []
    if r.status_code != 200:
        print(f"  {nome}: HTTP {r.status_code}", file=sys.stderr)
        return []
    try:
        return r.json().get("elements", [])
    except Exception as e:
        print(f"  {nome}: risposta illeggibile ({e})", file=sys.stderr)
        return []


def _tieni(dati: dict, griglia: dict) -> bool:
    """Il filtro geografico, diverso per tipo. Vedi il commento in cima."""
    if dati["tipo"] == "parcheggio":
        return vicino_a_una_gita(dati["lat"], dati["lon"], griglia,
                                 dominio.RAGGIO_PARCHEGGIO)
    if dati["tipo"] == "riparo":
        return vicino_a_una_gita(dati["lat"], dati["lon"], griglia,
                                 RAGGIO_RIPARI_DA_GITA)
    return True    # le piole: tutte quelle con un nome, il filtro e' a monte


def salva(elementi: list[dict], griglia: dict) -> dict:
    conteggi = {"nuovi": 0, "aggiornati": 0, "scartati": 0}
    with session_scope() as db:
        for e in elementi:
            dati = dominio.da_elemento(e)
            if not dati or not _tieni(dati, griglia):
                conteggi["scartati"] += 1
                continue
            c = comune_di(dati["lat"], dati["lon"]) or {}
            dati["istat"] = str(c["istat"]) if c.get("istat") else None

            p = (db.query(Posto)
                 .filter_by(fonte="osm", fonte_id=dati["fonte_id"]).one_or_none())
            if p is None:
                db.add(Posto(**dati))
                conteggi["nuovi"] += 1
            else:
                # si riscrive: in OSM la capienza viene aggiunta col tempo, e
                # un parcheggio che ieri non la dichiarava oggi puo' averla
                for campo, valore in dati.items():
                    setattr(p, campo, valore)
                conteggi["aggiornati"] += 1
    return conteggi


async def importa(quali: list[str] | None = None) -> dict:
    quali = quali or list(QUERY)
    with session_scope() as db:
        griglia = griglia_gite(db)
    if not griglia:
        print("! catalogo vuoto: importa prima le gite, i parcheggi si "
              "filtrano rispetto a quelle", file=sys.stderr)

    totali = {"nuovi": 0, "aggiornati": 0, "scartati": 0}
    async with httpx.AsyncClient(timeout=240,
                                 headers={"User-Agent": settings.user_agent}) as c:
        for nome in quali:
            elementi = await _scarica(c, nome)
            print(f"  {nome}: {len(elementi)} elementi da Overpass",
                  file=sys.stderr)
            conteggi = salva(elementi, griglia)
            print(f"  {nome}: {conteggi['nuovi']} nuovi, "
                  f"{conteggi['aggiornati']} aggiornati, "
                  f"{conteggi['scartati']} scartati", file=sys.stderr)
            for k in totali:
                totali[k] += conteggi[k]
            # Overpass e' un servizio gratuito con una coda condivisa: fra
            # due interrogazioni grosse si aspetta.
            await asyncio.sleep(3)
    return totali


if __name__ == "__main__":
    from app.db import init_db

    init_db()
    print(f"bbox: {settings.bbox}", file=sys.stderr)
    esito = asyncio.run(importa(sys.argv[1:] or None))
    print(f"posti: {esito['nuovi']} nuovi, {esito['aggiornati']} aggiornati",
          file=sys.stderr)
    print(dominio.ATTRIBUZIONE, file=sys.stderr)
    print(esito["nuovi"] + esito["aggiornati"])
