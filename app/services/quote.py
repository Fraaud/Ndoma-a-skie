"""Quote lungo una traccia, dal servizio quote di openrouteservice.

Perche' ORS e non un altro
--------------------------
La geometria che pubblica Camptocamp e' piatta: latitudine e longitudine,
niente quota. Per disegnare un profilo altimetrico le quote vanno prese da
un modello del terreno, e ne servivano una: ORS lo fa con **la stessa
chiave che usiamo gia'** per il percorso in auto, quindi zero configurazione
in piu' e un servizio in meno di cui fidarsi. (L'alternativa che avevamo
annotato, TrailSplits, non l'ho mai potuta provare: dal nostro ambiente e'
irraggiungibile, e non si costruisce una funzione su un servizio che non si
e' visto rispondere.)

Il limite dichiarato e' di **2000 vertici per richiesta**: le tracce si
semplificano prima, che e' comunque quello che serve per mandarle a un
telefono in valle.

Il dato che ne esce va trattato per quello che e': un modello del terreno a
maglia di qualche decina di metri. Va bene per disegnare la forma di una
salita, non per dire a qualcuno di quanti metri e' un salto di roccia.
"""
from __future__ import annotations

import sys

import httpx

from app import tracce
from app.config import settings


class QuoteNonDisponibili(RuntimeError):
    pass


async def quote_lungo(punti: list) -> tuple[list, str] | None:
    """Aggiunge la quota a ogni punto. None se il servizio non risponde.

    Restituisce (punti, sorgente). Non solleva per un errore di rete: una
    traccia senza profilo e' ancora una traccia, e il chiamante deve poter
    salvarla comunque.
    """
    if not settings.ors_api_key:
        return None
    if len(punti) < 2:
        return None
    if len(punti) > tracce.MAX_VERTICI:
        punti = tracce.semplifica(punti, tracce.TOLLERANZA_M * 2)
    if len(punti) > tracce.MAX_VERTICI:
        # ancora troppi: si tiene un punto ogni n, meglio che rinunciare
        passo = len(punti) // tracce.MAX_VERTICI + 1
        punti = punti[::passo]

    corpo = {
        "format_in": "geojson",
        "format_out": "geojson",
        "geometry": {
            "type": "LineString",
            # ORS vuole [lon, lat], noi teniamo [lat, lon]: e' il classico
            # scambio che non da' errore, disegna solo la traccia in Cina
            "coordinates": [[round(p[1], 6), round(p[0], 6)] for p in punti],
        },
    }
    intestazioni = {
        "Authorization": settings.ors_api_key,
        "Content-Type": "application/json",
        "User-Agent": settings.user_agent,
    }
    try:
        async with httpx.AsyncClient(timeout=40) as c:
            r = await c.post(settings.url_ors_elevation, json=corpo,
                             headers=intestazioni)
    except Exception as e:
        print(f"  quote: servizio non raggiungibile ({e})", file=sys.stderr)
        return None
    if r.status_code == 429:
        print("  quote: quota giornaliera esaurita, riprovo domani",
              file=sys.stderr)
        return None
    if r.status_code != 200:
        print(f"  quote: HTTP {r.status_code}", file=sys.stderr)
        return None

    try:
        coordinate = r.json()["geometry"]["coordinates"]
    except Exception as e:
        print(f"  quote: risposta illeggibile ({e})", file=sys.stderr)
        return None
    if len(coordinate) != len(punti):
        # e' documentato che possa succedere: si accetta solo se combacia,
        # altrimenti si appaierebbero quote a punti sbagliati
        print(f"  quote: tornati {len(coordinate)} punti su {len(punti)}, scarto",
              file=sys.stderr)
        return None

    fuori = []
    for (lon, lat, *resto) in coordinate:
        quota = round(float(resto[0]), 1) if resto else None
        fuori.append([round(lat, 6), round(lon, 6), quota])
    return fuori, "ors"


async def percorso_a_piedi(lat1: float, lon1: float,
                           lat2: float, lon2: float) -> list | None:
    """Una linea sui sentieri di OSM fra due punti. Con le quote comprese.

    ATTENZIONE, e non e' una nota tecnica: quello che torna da qui e' un
    PERCORSO CALCOLATO, e non va mostrato su una gita di scialpinismo.
    D'inverno non si sale per il sentiero estivo - si sale per i pendii, si
    evitano i traversi, si sceglie la linea in base alla neve. Vedi la nota
    in cima a app/tracce.py e `ORIGINI["calcolata"]["adatta_a_sci"]`.

    Sta qui perche' servira' alle camminate estive, non perche' si possa
    usare adesso.
    """
    if not settings.ors_api_key:
        return None
    corpo = {
        "coordinates": [[lon1, lat1], [lon2, lat2]],
        "elevation": True,
        "instructions": False,
    }
    intestazioni = {
        "Authorization": settings.ors_api_key,
        "Content-Type": "application/json",
        "User-Agent": settings.user_agent,
    }
    try:
        async with httpx.AsyncClient(timeout=40) as c:
            r = await c.post(settings.url_ors_a_piedi, json=corpo,
                             headers=intestazioni)
    except Exception as e:
        print(f"  percorso a piedi: non raggiungibile ({e})", file=sys.stderr)
        return None
    if r.status_code != 200:
        print(f"  percorso a piedi: HTTP {r.status_code}", file=sys.stderr)
        return None
    try:
        coordinate = r.json()["features"][0]["geometry"]["coordinates"]
    except Exception:
        return None
    return [[round(c_[1], 6), round(c_[0], 6),
             (round(float(c_[2]), 1) if len(c_) > 2 else None)]
            for c_ in coordinate]
