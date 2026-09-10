"""Parcheggi, ripari e piole: quello che OpenStreetMap sa dei posti.

Perche' esiste questo file
--------------------------
L'app e' nata da sei macchine ferme nello stesso piazzale. Il dato piu'
nostro che esista, quindi, e' **quanti posti ha quel piazzale**: OSM lo
tiene in `capacity`, e nessuna delle app di scialpinismo lo mostra.

Le tre cose stanno insieme perche' vengono dalla stessa interrogazione e si
usano nello stesso modo - "cosa c'e' vicino a questo punto" - ma si cercano
in due modi diversi, e la differenza e' importante:

- **parcheggi e ripari**: per distanza dall'attacco. Chi cerca un parcheggio
  lo cerca dove parte la gita, e chi cerca un riparo lo cerca dove si trova.
- **piole**: lungo il **corridoio del ritorno**, cioe' fra i comuni che il
  percorso attraversa. Cercarle "vicino all'attacco" non ha senso: a 1600 m
  di quota, a marzo, non c'e' niente di aperto. La piola dove ci si ferma e'
  in fondovalle, sulla strada di casa - ed e' esattamente il corridoio che
  calcoliamo gia' per i passaggi in auto.

Cosa NON facciamo
-----------------
Non mostriamo gli orari di apertura. OSM li ha (`opening_hours`), ma nelle
valli sono vecchi di anni: far credere a qualcuno che una piola e' aperta e'
peggio che non dirgli niente. Si mostra il telefono, che invecchia meno.

Non inventiamo la capienza. Se OSM non la dichiara, il campo resta vuoto e
l'app dice "capienza non indicata": e' un'informazione anche quella.
"""
from __future__ import annotations

import re
from typing import Optional

# Parcheggi che non si possono usare: meglio non mostrarli affatto che
# mandare qualcuno a sbattere contro una sbarra.
ACCESSI_CHIUSI = {"private", "no", "permit", "customers"}

# Cos'e' un riparo, in parole. Il genere conta piu' del nome: "rifugio
# gestito" e "bivacco non gestito" sono due cose molto diverse quando sta
# venendo buio.
RIPARI = {
    "alpine_hut": "rifugio gestito",
    "wilderness_hut": "bivacco, non gestito",
    "shelter": "tettoia o riparo",
}

# Che genere di piola. Non e' una classifica, e' cosa aspettarsi.
PIOLE = {
    "restaurant": "ristorante",
    "pub": "pub",
    "bar": "bar",
    "cafe": "caffe'",
}

# Raggi di ricerca, in chilometri.
#   parcheggio: l'attacco di una gita e il suo parcheggio sono la stessa
#     cosa a meno di poche centinaia di metri; 2 km prende anche il piazzale
#     piu' in basso dove si lascia l'auto quando la strada e' chiusa.
#   riparo: piu' largo, perche' in Emergenza serve sapere cosa c'e' intorno
#     anche se e' lontano - e mezz'ora di cammino sono un paio di chilometri.
RAGGIO_PARCHEGGIO = 2.0
RAGGIO_RIPARO = 6.0

ATTRIBUZIONE = "Parcheggi, ripari e piole da OpenStreetMap (ODbL)"

# I tag che teniamo. Il resto si butta: un giorno serviranno altre cose e
# si aggiungeranno qui, ma copiare tutto vorrebbe dire tenersi in casa mezza
# banca dati per usarne tre campi.
DETTAGLI_UTILI = ("fee", "surface", "phone", "website", "cuisine",
                  "shelter_type", "operator", "parking")


def capienza(tags: dict) -> Optional[int]:
    """Il `capacity` di OSM, che nella realta' non e' sempre un numero.

    In giro si trovano "12", "~20", "10;5", "yes", "10-15", "circa 30".
    Si prende il primo numero e si ignora il resto: "yes" non e' una
    capienza e diventa None, che l'app sa dire ("capienza non indicata").
    """
    grezzo = str(tags.get("capacity", "")).strip()
    if not grezzo:
        return None
    m = re.search(r"\d+", grezzo)
    if not m:
        return None
    n = int(m.group())
    # oltre il migliaio non e' un parcheggio di partenza gita, e' un errore
    # di battitura o un centro commerciale
    return n if 0 < n <= 1000 else None


def quota(tags: dict) -> Optional[int]:
    """Il tag `ele`, in metri. Anche questo a volte e' scritto a mano."""
    m = re.search(r"-?\d+", str(tags.get("ele", "")))
    if not m:
        return None
    n = int(m.group())
    return n if -100 <= n <= 5000 else None


def classifica(tags: dict) -> Optional[str]:
    """Che genere di posto e', secondo i tag. None se non ci interessa."""
    if tags.get("tourism") in ("alpine_hut", "wilderness_hut"):
        return "riparo"
    if tags.get("amenity") == "shelter":
        # le fermate dell'autobus sono taggate shelter: non sono ripari di
        # montagna e in Emergenza sarebbero un consiglio sbagliato
        if tags.get("shelter_type") in ("public_transport", "picnic_shelter"):
            return None
        return "riparo"
    if tags.get("amenity") == "parking":
        return "parcheggio"
    if tags.get("amenity") in PIOLE:
        return "piola"
    return None


def genere(tipo: str, tags: dict) -> Optional[str]:
    if tipo == "riparo":
        if tags.get("tourism") in RIPARI:
            return RIPARI[tags["tourism"]]
        return RIPARI["shelter"]
    if tipo == "piola":
        return PIOLE.get(tags.get("amenity", ""))
    if tipo == "parcheggio":
        return None
    return None


def utilizzabile(tipo: str, tags: dict) -> bool:
    """Un parcheggio privato non e' un parcheggio: non lo mostriamo."""
    if tipo != "parcheggio":
        return True
    return str(tags.get("access", "")).strip().lower() not in ACCESSI_CHIUSI


def da_elemento(e: dict) -> Optional[dict]:
    """Un elemento Overpass -> i campi del modello. None se va scartato.

    Difensiva di proposito: e' l'unico punto in cui entrano dati di cui non
    controlliamo la forma, e un `way` senza `center` o un tag scritto a mano
    non devono far cadere l'import di tutto il resto.
    """
    if not isinstance(e, dict):
        return None
    tags = e.get("tags") or {}
    if not isinstance(tags, dict):
        return None
    tipo = classifica(tags)
    if not tipo or not utilizzabile(tipo, tags):
        return None

    centro = e.get("center") or {}
    lat = e.get("lat", centro.get("lat"))
    lon = e.get("lon", centro.get("lon"))
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None

    nome = str(tags.get("name") or "").strip()[:160] or None
    # una piola senza nome non e' utilizzabile: nessuno cerca "un bar"
    if tipo == "piola" and not nome:
        return None

    return {
        "tipo": tipo,
        "fonte": "osm",
        "fonte_id": f"{e.get('type', 'node')}/{e.get('id', '')}",
        "nome": nome,
        "lat": lat, "lon": lon,
        "quota": quota(tags),
        "capienza": capienza(tags) if tipo == "parcheggio" else None,
        "genere": genere(tipo, tags),
        "dettagli": {k: str(tags[k])[:120] for k in DETTAGLI_UTILI if tags.get(k)},
    }


def url_osm(fonte_id: str) -> str:
    return f"https://www.openstreetmap.org/{fonte_id}"


def etichetta(p) -> str:
    """Come si chiama, quando OSM non gli ha dato un nome.

    La maggioranza dei parcheggi non ha `name`: "Parcheggio" e' un'etichetta
    onesta, e quello che serve davvero (quanti posti, quanto lontano) sta
    accanto.
    """
    if p.nome:
        return p.nome
    if p.tipo == "parcheggio":
        return "Parcheggio senza nome"
    if p.tipo == "riparo":
        return (p.genere or "Riparo").capitalize()
    return "Senza nome"


def capienza_in_parole(p) -> str:
    if p.tipo != "parcheggio":
        return ""
    if p.capienza is None:
        return "capienza non indicata"
    if p.capienza == 1:
        return "1 posto"
    return f"{p.capienza} posti"


def posto_dict(p, distanza_km: float | None = None) -> dict:
    d = {
        "id": p.id, "tipo": p.tipo, "nome": p.nome, "etichetta": etichetta(p),
        "lat": p.lat, "lon": p.lon, "quota": p.quota,
        "capienza": p.capienza, "capienza_testo": capienza_in_parole(p),
        "genere": p.genere, "dettagli": p.dettagli or {},
        "osm_url": url_osm(p.fonte_id),
    }
    if distanza_km is not None:
        d["distanza_km"] = round(distanza_km, 1)
        d["distanza_m"] = int(round(distanza_km * 1000, -1))
    return d


# --------------------------------------------------------------- ricerca


def _gradi_per_km(lat: float) -> tuple[float, float]:
    """Quanto vale un chilometro in gradi, a questa latitudine.

    Serve solo a fare un riquadro grossolano per l'indice del database:
    la distanza vera la calcola poi distanza_km, una per candidato.
    """
    import math

    return 1 / 111.0, 1 / max(0.1, 111.0 * math.cos(math.radians(lat)))


def vicini(db, lat: float, lon: float, tipo: str, entro_km: float,
           limite: int = 6) -> list[tuple]:
    """I posti di quel tipo entro `entro_km`, dal piu' vicino.

    Prima un riquadro (che usa l'indice su lat/lon), poi la distanza vera
    solo sui candidati: senza il riquadro sarebbe una radice quadrata per
    ognuno dei posti in archivio, a ogni apertura di scheda.
    """
    from app.geo import distanza_km
    from app.models import Posto

    dlat, dlon = _gradi_per_km(lat)
    righe = (db.query(Posto)
             .filter(Posto.tipo == tipo,
                     Posto.lat.between(lat - entro_km * dlat, lat + entro_km * dlat),
                     Posto.lon.between(lon - entro_km * dlon, lon + entro_km * dlon))
             .limit(400).all())
    con_distanza = [(p, distanza_km(lat, lon, p.lat, p.lon)) for p in righe]
    dentro = [(p, d) for p, d in con_distanza if d <= entro_km]
    dentro.sort(key=lambda x: x[1])
    return dentro[:limite]


def in_comuni(db, istat: list[str], tipo: str = "piola", limite: int = 12) -> list:
    """I posti nei comuni indicati: e' cosi' che si cercano le piole.

    L'ordine non e' casuale: `istat` arriva dal percorso, quindi e' l'ordine
    in cui si attraversano i paesi tornando a casa. Le piole si mostrano
    nello stesso ordine, che e' quello in cui uno le incontra.
    """
    from app.models import Posto

    if not istat:
        return []
    righe = (db.query(Posto)
             .filter(Posto.tipo == tipo, Posto.istat.in_(istat))
             .limit(300).all())
    posizione = {codice: i for i, codice in enumerate(istat)}
    righe.sort(key=lambda p: (posizione.get(p.istat or "", 999), p.nome or ""))
    return righe[:limite]
