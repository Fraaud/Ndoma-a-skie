"""Bollettino valanghe: RIPORTIAMO, NON VALUTIAMO.

Regole di prodotto, non negoziabili:
  1. Nessun grado di pericolo calcolato da noi. Solo quello ufficiale EAWS.
  2. Nessun semaforo verde, nessun "si puo' andare". Mai.
  3. Sempre visibili: ente emittente, ora di emissione, link al bollettino integrale.
  4. L'evidenziatore incrocia due dati oggettivi (esposizione/quota della gita
     contro esposizione/quota del problema segnalato). E' un evidenziatore,
     non un giudizio di sicurezza.

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


# --------------------------------------------------------- evidenziatore


def _range_si_sovrappone(a_min, a_max, b_min, b_max) -> bool:
    a_min = a_min if a_min is not None else -9999
    a_max = a_max if a_max is not None else 9999
    b_min = b_min if b_min is not None else -9999
    b_max = b_max if b_max is not None else 9999
    return a_min <= b_max and b_min <= a_max


def evidenzia(gita: Any, bollettino: dict | None) -> list[dict]:
    """Incrocia esposizione e fascia di quota della gita con i problemi segnalati.

    NON dice se la gita e' sicura. Dice: "il bollettino parla di questo, e la
    tua gita ci passa dentro". La decisione resta a chi va, sul bollettino
    integrale e sul terreno.
    """
    if not bollettino:
        return []
    esp_gita = normalizza_esposizioni(getattr(gita, "esposizione", None))
    q_min = getattr(gita, "quota_min", None)
    q_max = getattr(gita, "quota_max", None)

    avvisi = []
    for p in bollettino.get("problemi", []):
        if p["tipo"] == "favourable_situation":
            continue
        quota_ok = _range_si_sovrappone(q_min, q_max, p["quota_min"], p["quota_max"])
        esp_comuni = [e for e in esp_gita if e in p["esposizioni"]] if p["esposizioni"] else []
        # se non conosciamo l'esposizione della gita, non filtriamo: meglio
        # mostrare in piu' che in meno.
        esp_ok = bool(esp_comuni) or not esp_gita or not p["esposizioni"]
        if quota_ok and esp_ok:
            # `testo` contiene solo i dettagli: il nome del problema sta gia'
            # nel campo `problema` e l'interfaccia lo mostra separatamente.
            pezzi = []
            if p["esposizioni"]:
                pezzi.append("esposizioni " + "-".join(p["esposizioni"]))
            if p["quota_min"]:
                pezzi.append(f"sopra {p['quota_min']} m")
            if p["quota_max"]:
                pezzi.append(f"sotto {p['quota_max']} m")
            avvisi.append({
                "problema": p["tipo_it"],
                "testo": ", ".join(pezzi) if pezzi else "su tutte le esposizioni e quote",
                "esposizioni_in_comune": esp_comuni,
                "rilevanza": "alta" if esp_comuni else "possibile",
            })
    return avvisi


def link_bollettino_ufficiale(paese: str = "IT", regione_eaws: str | None = None) -> str:
    if paese == "FR":
        return "https://meteofrance.com/meteo-montagne/bulletin-avalanches"
    return settings.url_aineva_bulletin.format(province="IT-21")


DISCLAIMER = (
    "Dati riportati dal bollettino ufficiale a scopo informativo. Fa fede sempre il "
    "bollettino integrale dell'ente emittente, che va letto prima di ogni uscita. "
    "Questa app non valuta la sicurezza di un itinerario."
)
