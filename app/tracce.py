"""La traccia di un itinerario: da dove viene, come si semplifica, come si esporta.

Perche' la PROVENIENZA e' il concetto centrale
----------------------------------------------
Una linea su una mappa, in montagna, e' un invito a seguirla. Quindi conta
piu' di tutto sapere chi l'ha disegnata:

- `fonte`     la geometria pubblicata dalla fonte aperta (Camptocamp,
              CC-BY-SA). L'ha disegnata o registrata qualcuno che ha fatto
              quella gita. E' la traccia buona, e va attribuita.
- `utente`    la registrazione di chi usa l'app: la sua, dal suo GPS.
              La migliore che possiamo avere delle nostre valli.
- `calcolata` un percorso costruito da noi facendo passare una linea sui
              sentieri di OpenStreetMap. Non e' la traccia di nessuno.

L'ultima ha un limite che non e' un dettaglio tecnico ma una regola di
sicurezza: **una linea calcolata sui sentieri estivi non e' una gita di
scialpinismo**. D'inverno non si sale per il sentiero - si sale per i
pendii, si evitano i traversi, si sceglie la linea in base alla neve e al
terreno valanghivo. Mostrare una linea "verosimile" su una gita di sci
vorrebbe dire mettere in mano a qualcuno un itinerario che nessuno ha
percorso, in un terreno dove la scelta della linea e' la decisione che
conta. Per questo `ORIGINI[...]["adatta_a_sci"]` esiste, e per questo c'e'
un test che lo verifica.

Sui dislivelli
--------------
Il dislivello calcolato sommando i saltini di un profilo campionato da un
modello del terreno **sovrastima sempre**: il rumore del modello diventa
salita. Quindi: se la fonte dichiara il dislivello, si mostra il suo. Il
nostro serve solo per accorgersi che uno dei due e' assurdo - vedi
`plausibile()`.
"""
from __future__ import annotations

import datetime as dt
import math
import xml.etree.ElementTree as ET
from typing import Iterable, Optional

# Le tre provenienze, con le parole con cui si presentano all'utente.
ORIGINI = {
    "fonte": {
        "etichetta": "traccia della fonte",
        "spiega": "Pubblicata dalla fonte dell'itinerario, con la sua licenza.",
        "adatta_a_sci": True,
    },
    "utente": {
        "etichetta": "registrata da chi c'e' andato",
        "spiega": "Caricata da una persona che ha fatto questa gita.",
        "adatta_a_sci": True,
    },
    "calcolata": {
        "etichetta": "percorso calcolato",
        "spiega": ("Costruito facendo passare una linea sui sentieri di "
                   "OpenStreetMap: e' un'ipotesi, non la traccia di una gita. "
                   "D'inverno la linea giusta la scegli tu sul posto, in base "
                   "alla neve."),
        "adatta_a_sci": False,
    },
}

# Il modello del terreno che usiamo per le quote ha una maglia di ~30 m:
# semplificare sotto quella soglia non toglie informazione, toglie peso.
TOLLERANZA_M = 12.0

# Il servizio quote di openrouteservice accetta al massimo 2000 vertici per
# richiesta. Non li spezziamo in due chiamate: si semplifica prima, che e'
# comunque quello che vogliamo per il telefono.
MAX_VERTICI = 2000

# Meno di questo non e' una traccia, e' un paio di punti.
MIN_PUNTI = 8

# Il rumore del modello del terreno: sotto questa soglia un saltino di quota
# non e' salita, e sommarlo gonfia il dislivello.
#
# Otto metri e non quattro, e il numero l'ha scelto un test: su un profilo
# che oscilla di +/-2 m - normalissimo per un modello del terreno - i salti
# fra un campione e il successivo sono di 4 m, e una soglia di 4 li contava
# tutti, inventando 400 m di dislivello su un pianoro.
#
# La soglia non mangia la salita vera: il confronto e' con l'ultima quota
# ACCETTATA, non con la precedente, quindi una scaletta di gradini da 5 m
# tutti in salita viene contata per intero. Filtra l'oscillazione, non la
# pendenza - c'e' un test anche per questo.
SOGLIA_RUMORE_M = 8.0


# ------------------------------------------------------------- geometria


def _metri_per_grado(lat: float) -> tuple[float, float]:
    return 111_320.0, 111_320.0 * max(0.05, math.cos(math.radians(lat)))


def distanza_m(a: Iterable[float], b: Iterable[float]) -> float:
    """Distanza piana fra due punti (lat, lon). Su scale di valle basta."""
    (la1, lo1), (la2, lo2) = (a[0], a[1]), (b[0], b[1])
    mlat, mlon = _metri_per_grado((la1 + la2) / 2)
    return math.hypot((la2 - la1) * mlat, (lo2 - lo1) * mlon)


def _distanza_da_segmento(p, a, b) -> float:
    mlat, mlon = _metri_per_grado(p[0])
    px, py = p[1] * mlon, p[0] * mlat
    ax, ay = a[1] * mlon, a[0] * mlat
    bx, by = b[1] * mlon, b[0] * mlat
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def semplifica(punti: list, tolleranza_m: float = TOLLERANZA_M) -> list:
    """Douglas-Peucker, iterativo.

    Serve a due cose diverse con lo stesso strumento: mandare al telefono
    duecento punti invece di duemila (in valle si naviga con una tacca), e
    stare sotto il tetto di vertici del servizio quote. La forma della
    linea non cambia: si tolgono i punti che stanno a meno di una decina di
    metri dalla linea che li unisce, cioe' dentro l'errore del GPS.

    Iterativo e non ricorsivo di proposito: su una traccia lunga la
    ricorsione arriverebbe al limite di python.
    """
    if len(punti) <= 2:
        return list(punti)
    tenere = [False] * len(punti)
    tenere[0] = tenere[-1] = True
    pile = [(0, len(punti) - 1)]
    while pile:
        i, j = pile.pop()
        if j <= i + 1:
            continue
        peggiore, distanza = -1, 0.0
        for k in range(i + 1, j):
            d = _distanza_da_segmento(punti[k], punti[i], punti[j])
            if d > distanza:
                peggiore, distanza = k, d
        if distanza > tolleranza_m and peggiore > 0:
            tenere[peggiore] = True
            pile.append((i, peggiore))
            pile.append((peggiore, j))
    return [p for p, s in zip(punti, tenere) if s]


def lunghezza_km(punti: list) -> float:
    return round(sum(distanza_m(punti[i], punti[i + 1])
                     for i in range(len(punti) - 1)) / 1000.0, 2)


def dislivelli(punti: list, soglia_m: float = SOGLIA_RUMORE_M) -> tuple[int, int]:
    """Salita e discesa accumulate, ignorando il rumore del modello.

    Vedi la nota in cima: questo numero SOVRASTIMA e non sostituisce quello
    dichiarato dalla fonte. Serve al controllo di plausibilita'.
    """
    su = giu = 0.0
    riferimento = None
    for p in punti:
        if len(p) < 3 or p[2] is None:
            continue
        q = float(p[2])
        if riferimento is None:
            riferimento = q
            continue
        delta = q - riferimento
        if abs(delta) < soglia_m:
            continue
        if delta > 0:
            su += delta
        else:
            giu -= delta
        riferimento = q
    return int(round(su)), int(round(giu))


def con_quote(punti: list) -> bool:
    return bool(punti) and any(len(p) >= 3 and p[2] is not None for p in punti)


def plausibile(dichiarato: Optional[int], calcolato: Optional[int]) -> Optional[bool]:
    """Il dislivello dichiarato regge il confronto con la traccia?

    None quando non si puo' dire. Il margine e' larghissimo di proposito
    (il calcolato sovrastima, e la traccia puo' coprire solo una parte
    dell'itinerario): serve a pescare gli errori grossolani - un 4618 m su
    una gita da 900 - non a fare le pulci a nessuno.
    """
    if not dichiarato or not calcolato:
        return None
    if dichiarato < 50 or calcolato < 50:
        return None
    rapporto = dichiarato / calcolato
    return 0.4 <= rapporto <= 2.5


def profilo(punti: list, passi: int = 90) -> list:
    """Il profilo altimetrico ridotto a `passi` campioni (distanza, quota).

    Si campiona a distanza costante e non per indice: i punti di una traccia
    sono piu' densi dove si curva, e un profilo per indice disegnerebbe le
    curve larghe e i rettilinei stretti.
    """
    quotati = [p for p in punti if len(p) >= 3 and p[2] is not None]
    if len(quotati) < 2:
        return []
    cumulata = [0.0]
    for i in range(len(quotati) - 1):
        cumulata.append(cumulata[-1] + distanza_m(quotati[i], quotati[i + 1]))
    totale = cumulata[-1]
    if totale <= 0:
        return []

    fuori, j = [], 0
    for s in range(passi + 1):
        bersaglio = totale * s / passi
        while j < len(cumulata) - 2 and cumulata[j + 1] < bersaglio:
            j += 1
        # interpolazione lineare fra i due punti che lo contengono
        d0, d1 = cumulata[j], cumulata[j + 1]
        q0, q1 = float(quotati[j][2]), float(quotati[j + 1][2])
        t = 0.0 if d1 == d0 else (bersaglio - d0) / (d1 - d0)
        fuori.append([round(bersaglio / 1000.0, 3), round(q0 + (q1 - q0) * t, 1)])
    return fuori


# ------------------------------------------------------------------ GPX


def _testo(padre, tag: str, valore) -> None:
    if valore in (None, ""):
        return
    e = ET.SubElement(padre, tag)
    e.text = str(valore)


def gpx(gita, traccia) -> str:
    """Un GPX con l'attribuzione DENTRO il file.

    Sulla scheda l'attribuzione si vede; in un file che gira per WhatsApp e
    finisce su un altro telefono, no. CC-BY-SA obbliga a portarla con se',
    e il posto dove metterla e' `<metadata>`: `<copyright>` con la licenza e
    `<link>` alla pagina della fonte. Un GPX che perde la provenienza e' un
    dato orfano, ed e' il modo in cui i cataloghi altrui finiscono dove non
    dovrebbero.
    """
    origine = ORIGINI.get(traccia.origine, {})
    gpx_el = ET.Element("gpx", {
        "version": "1.1",
        "creator": "Ndoma a skie'",
        "xmlns": "http://www.topografix.com/GPX/1/1",
    })
    meta = ET.SubElement(gpx_el, "metadata")
    _testo(meta, "name", gita.nome)
    descrizione = [origine.get("etichetta", traccia.origine), origine.get("spiega", "")]
    if traccia.origine == "fonte" and traccia.autori:
        descrizione.append(f"Autori: {traccia.autori}.")
    descrizione.append(
        "Il grado di pericolo valanghe e le condizioni non stanno in questo "
        "file: leggi il bollettino ufficiale prima di uscire."
    )
    _testo(meta, "desc", " ".join(x for x in descrizione if x))
    if traccia.licenza:
        cop = ET.SubElement(meta, "copyright", {"author": traccia.autori or traccia.licenza})
        _testo(cop, "license", traccia.licenza)
    if gita.fonte_url:
        ET.SubElement(meta, "link", {"href": gita.fonte_url}).append(
            _elemento_testo("text", gita.fonte or "fonte"))
    _testo(meta, "time", dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    trk = ET.SubElement(gpx_el, "trk")
    _testo(trk, "name", gita.nome)
    _testo(trk, "type", "scialpinismo")
    seg = ET.SubElement(trk, "trkseg")
    for p in traccia.punti or []:
        pt = ET.SubElement(seg, "trkpt", {"lat": f"{p[0]:.6f}", "lon": f"{p[1]:.6f}"})
        if len(p) >= 3 and p[2] is not None:
            _testo(pt, "ele", f"{float(p[2]):.1f}")

    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            + ET.tostring(gpx_el, encoding="unicode"))


def _elemento_testo(tag: str, valore: str):
    e = ET.Element(tag)
    e.text = valore
    return e


def nome_file(gita) -> str:
    """Un nome di file che si riconosce nella cartella dei download."""
    pulito = "".join(c if c.isalnum() or c in " -_" else "" for c in (gita.nome or "gita"))
    return "ndoma-" + "-".join(pulito.lower().split())[:60] + ".gpx"


# --------------------------------------------------- lettura di un GPX


class GpxNonValido(ValueError):
    pass


def da_gpx(contenuto: str, bbox: tuple | None = None, massimo: int = 20000) -> list:
    """I punti di un GPX caricato da una persona.

    Difensiva come l'ingresso da Overpass, per la stessa ragione: e' un
    file che arriva da fuori. Si accettano tracce (`trkpt`) e itinerari
    (`rtept`), si ignora tutto il resto - i `wpt` sparsi non sono una
    traccia.
    """
    try:
        radice = ET.fromstring(contenuto.strip())
    except ET.ParseError as e:
        raise GpxNonValido(f"non e' un file GPX leggibile ({e})")

    punti: list = []
    for tag in ("trkpt", "rtept"):
        for e in radice.iter():
            if not e.tag.endswith(tag):
                continue
            try:
                lat, lon = float(e.get("lat")), float(e.get("lon"))
            except (TypeError, ValueError):
                continue
            quota = None
            for figlio in e:
                if figlio.tag.endswith("ele") and (figlio.text or "").strip():
                    try:
                        quota = round(float(figlio.text), 1)
                    except ValueError:
                        quota = None
            punti.append([lat, lon, quota] if quota is not None else [lat, lon])
            if len(punti) > massimo:
                raise GpxNonValido("file troppo grande: piu' di "
                                   f"{massimo} punti")
        if punti:
            break

    if len(punti) < MIN_PUNTI:
        raise GpxNonValido("ci sono meno di otto punti: non e' una traccia")
    if bbox:
        ovest, sud, est, nord = bbox
        dentro = sum(1 for p in punti if sud <= p[0] <= nord and ovest <= p[1] <= est)
        if dentro < len(punti) * 0.6:
            raise GpxNonValido("questa traccia non e' nella zona coperta "
                               "dall'app (Cuneese e Mercantour)")
    return punti


def vicina_alla_gita(punti: list, lat: float, lon: float, entro_km: float = 3.0) -> bool:
    """La traccia caricata parte davvero da questa gita?

    Senza questo controllo il primo caricamento sbagliato mette la traccia
    del Monviso sulla scheda della Meja, e non se ne accorge nessuno.
    """
    if not punti:
        return False
    metri = entro_km * 1000
    return any(distanza_m(p, (lat, lon)) <= metri for p in (punti[0], punti[-1]))


def salva(db, gita, punti: list, origine: str, licenza: str | None = None,
          autori: str | None = None, caricata_da: int | None = None,
          quote_da: str | None = None):
    """Scrive (o riscrive) la traccia di una gita, coi conti gia' fatti.

    Una gita ha una traccia sola, e una migliore prende il posto della
    peggiore: una registrata da una persona vale piu' di una calcolata.
    L'ordine di preferenza e' qui, in un posto solo, invece che sparso fra
    l'importatore e l'endpoint di caricamento.
    """
    from app.models import Traccia

    if origine not in ORIGINI:
        raise ValueError(f"origine sconosciuta: {origine}")
    if len(punti) < MIN_PUNTI:
        raise ValueError("meno di otto punti: non e' una traccia")

    su, giu = dislivelli(punti)
    t = db.query(Traccia).filter_by(gita_id=gita.id).one_or_none()
    if t is None:
        t = Traccia(gita_id=gita.id)
        db.add(t)
    t.origine = origine
    t.punti = punti
    t.quote_da = quote_da if con_quote(punti) else None
    t.lunghezza_km = lunghezza_km(punti)
    t.dislivello_su = su or None
    t.dislivello_giu = giu or None
    t.licenza = licenza
    t.autori = autori
    t.caricata_da = caricata_da
    t.aggiornata_il = dt.datetime.now(dt.timezone.utc)
    return t


# Quale traccia vince, quando ne arriva una nuova: piu' alto e' meglio.
PREFERENZA = {"calcolata": 0, "fonte": 1, "utente": 2}


def sostituisce(vecchia_origine: str | None, nuova_origine: str) -> bool:
    """Una traccia nuova prende il posto di quella vecchia?

    Sostituire sempre vorrebbe dire che un re-import notturno cancella la
    registrazione GPS di una persona per rimetterci la linea della fonte.
    """
    if vecchia_origine is None:
        return True
    if vecchia_origine == nuova_origine:
        return True          # aggiornamento della stessa provenienza
    return PREFERENZA.get(nuova_origine, 0) > PREFERENZA.get(vecchia_origine, 0)


def traccia_dict(traccia, gita=None, semplificata: bool = True) -> dict:
    punti = list(traccia.punti or [])
    if semplificata:
        punti = semplifica(punti)
    origine = ORIGINI.get(traccia.origine, {})
    calcolato = traccia.dislivello_su
    return {
        "origine": traccia.origine,
        "origine_etichetta": origine.get("etichetta", traccia.origine),
        "origine_spiega": origine.get("spiega", ""),
        "adatta_a_sci": origine.get("adatta_a_sci", False),
        "punti": punti,
        "punti_totali": len(traccia.punti or []),
        "con_quote": con_quote(traccia.punti or []),
        "quote_da": traccia.quote_da,
        "lunghezza_km": traccia.lunghezza_km,
        # il dislivello che mostriamo e' quello DICHIARATO dalla fonte; il
        # nostro sta accanto, dichiarato per quello che e'
        "dislivello_dichiarato": getattr(gita, "dislivello", None) if gita else None,
        "dislivello_dalla_traccia": calcolato,
        "dislivello_plausibile": plausibile(
            getattr(gita, "dislivello", None) if gita else None, calcolato),
        "profilo": profilo(traccia.punti or []),
        "licenza": traccia.licenza,
        "autori": traccia.autori,
    }
