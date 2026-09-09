"""Bollettino valanghe: SI RIPORTA E BASTA.

Regole di prodotto, non negoziabili:
  1. Nessun grado di pericolo calcolato da noi. Solo quello ufficiale EAWS.
  2. Nessun semaforo verde, nessun "si puo' andare". Mai.
  3. Sempre visibili: ente emittente, ora di emissione, link al bollettino integrale.
  4. Nessun incrocio fra il bollettino e i dati della gita. Nessuna
     evidenziazione di quali problemi "ti riguardano": scegliere cosa mettere
     in risalto e' gia' interpretare, e implica che il resto non ti riguardi.
     Il bollettino si mostra intero, nell'ordine in cui e' stato scritto.

Fonti:
  - micro-regioni EAWS: regions.avalanches.org (GeoJSON)
  - bollettini aggregati CAAMLv6: static.avalanche.report/eaws_bulletins/
  - Piemonte: emesso da ARPA Piemonte, ridistribuito da AINEVA
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

import httpx

from app.config import settings

GRADI = {
    "low": (1, "Debole"),
    "moderate": (2, "Moderato"),
    "considerable": (3, "Marcato"),
    "high": (4, "Forte"),
    "very_high": (5, "Molto forte"),
    "no_rating": (0, "Non emesso"),
    "no_snow": (0, "Assenza di neve"),
}

PROBLEMI = {
    "new_snow": "Neve fresca",
    "wind_slab": "Lastroni da vento",
    "persistent_weak_layers": "Strato debole persistente",
    "wet_snow": "Neve bagnata",
    "gliding_snow": "Valanghe di slittamento",
    "favourable_situation": "Situazione favorevole",
}

# normalizzazione esposizioni: il bollettino usa sigle inglesi, noi anche italiane
_ESP = {
    "N": "N", "NE": "NE", "E": "E", "SE": "SE", "S": "S",
    "SW": "SO", "W": "O", "NW": "NO",
    "SO": "SO", "O": "O", "NO": "NO",
}
ORDINE_ESP = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]


def normalizza_esposizioni(valori: Any) -> list[str]:
    if not valori:
        return []
    if isinstance(valori, str):
        valori = re.split(r"[,\s;/]+", valori)
    out = []
    for v in valori:
        k = str(v).strip().upper()
        if k in _ESP and _ESP[k] not in out:
            out.append(_ESP[k])
    return [e for e in ORDINE_ESP if e in out]


# --------------------------------------------------------------- download


async def _elenco_file(client: httpx.AsyncClient, giorno: dt.date) -> list[str]:
    """L'archivio espone un indice HTML per data: ne estraiamo i .json.
    Fare discovery invece di indovinare il nome file rende il tutto immune
    ai cambi di convenzione a monte."""
    url = settings.url_eaws_bulletins_dir.format(date=giorno.isoformat())
    r = await client.get(url)
    if r.status_code != 200:
        return []
    nomi = [n.split("/")[-1] for n in re.findall(r'href="([^"?]+\.json)"', r.text)]
    # L'archivio pubblica, accanto al bollettino completo, due estratti:
    #   2026-01-15-IT-21.problems.json   e   ....ratings.json
    # Scaricarli sarebbe inutile (sono sottoinsiemi) e li parseremmo come se
    # fossero bollettini interi.
    return [n for n in nomi if not n.endswith((".problems.json", ".ratings.json"))]


async def scarica_bollettini(
    giorno: dt.date | None = None,
    prefissi: tuple[str, ...] = ("IT-21", "FR", "IT-MeteoMont"),
) -> dict[str, dict]:
    """Scarica i bollettini del giorno e restituisce {region_id: bollettino_normalizzato}."""
    giorno = giorno or dt.date.today()
    base = settings.url_eaws_bulletins_dir.format(date=giorno.isoformat())
    risultato: dict[str, dict] = {}

    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": settings.user_agent},
                                 follow_redirects=True) as c:
        nomi = await _elenco_file(c, giorno)
        interessanti = [n for n in nomi if any(p.replace("-", "") in n.replace("-", "")
                                               for p in prefissi)] or nomi
        for nome in interessanti:
            try:
                r = await c.get(base + nome)
                if r.status_code != 200:
                    continue
                payload = r.json()
            except Exception:
                continue
            for b in _estrai_bollettini(payload):
                norm = normalizza(b, fonte_url=base + nome)
                for rid in norm["regioni"]:
                    risultato[rid] = norm
    return risultato


def _estrai_bollettini(payload: Any) -> list[dict]:
    """CAAMLv6 puo' arrivare come {"bulletins": [...]} o come lista nuda."""
    if isinstance(payload, dict):
        for chiave in ("bulletins", "Bulletins", "bulletin"):
            if isinstance(payload.get(chiave), list):
                return payload[chiave]
        return [payload]
    if isinstance(payload, list):
        return payload
    return []


# --------------------------------------------------------------- parsing


def _quota(el: Any) -> tuple[int | None, int | None]:
    """(quota_min, quota_max) di validita' del rating/problema."""
    if not isinstance(el, dict):
        return None, None
    def _n(v):
        try:
            return int(float(str(v).replace("m", "").strip()))
        except Exception:
            return None
    return _n(el.get("lowerBound")), _n(el.get("upperBound"))


def normalizza(b: dict, fonte_url: str | None = None) -> dict:
    regioni = []
    for r in b.get("regions", []) or []:
        rid = r.get("regionID") or r.get("regionId") or r.get("id")
        if rid:
            regioni.append(rid)

    gradi = []
    for d in b.get("dangerRatings", []) or []:
        chiave = str(d.get("mainValue", "")).lower()
        numero, testo = GRADI.get(chiave, (None, chiave or "?"))
        lo, hi = _quota(d.get("elevation"))
        gradi.append({
            "grado": numero, "testo": testo,
            "periodo": d.get("validTimePeriod"),
            "quota_min": lo, "quota_max": hi,
        })

    problemi = []
    for p in b.get("avalancheProblems", []) or []:
        tipo = str(p.get("problemType", "")).lower()
        lo, hi = _quota(p.get("elevation"))
        problemi.append({
            "tipo": tipo,
            "tipo_it": PROBLEMI.get(tipo, tipo.replace("_", " ")),
            "esposizioni": normalizza_esposizioni(p.get("aspects")),
            "quota_min": lo, "quota_max": hi,
            "periodo": p.get("validTimePeriod"),
        })

    def _testo(chiave: str) -> str | None:
        v = b.get(chiave)
        if isinstance(v, list) and v:
            v = v[0]
        if isinstance(v, dict):
            return v.get("highlights") or v.get("comment")
        return v if isinstance(v, str) else None

    valido = b.get("validTime") or {}
    return {
        "regioni": regioni,
        "grado_massimo": max([g["grado"] for g in gradi if g["grado"] is not None] or [None]) if gradi else None,
        "gradi": gradi,
        "problemi": problemi,
        "sintesi": _testo("highlights") or _testo("avalancheActivity"),
        "innevamento": _testo("snowpackStructure"),
        "valido_da": valido.get("startTime"),
        "valido_a": valido.get("endTime"),
        "emesso_il": b.get("publicationTime"),
        "ente": (b.get("source", {}) or {}).get("provider", {}).get("name")
                if isinstance(b.get("source"), dict) else None,
        "fonte_url": fonte_url,
    }


def link_bollettino_ufficiale(paese: str = "IT", regione_eaws: str | None = None) -> str:
    if paese == "FR":
        return "https://meteofrance.com/meteo-montagne/bulletin-avalanches"
    return settings.url_aineva_bulletin.format(province="IT-21")


DISCLAIMER = (
    "Dati riportati dal bollettino ufficiale a scopo informativo. Fa fede sempre il "
    "bollettino integrale dell'ente emittente, che va letto prima di ogni uscita. "
    "Questa app non valuta la sicurezza di un itinerario."
)
