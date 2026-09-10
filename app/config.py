"""Configurazione centrale, letta da .env."""
from __future__ import annotations

import os
import sys
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Su Railway (o ovunque ci sia un volume) si punta la cartella dati altrove:
# e' l'unico posto che deve sopravvivere ai riavvii.
DATA_DIR = os.getenv("DATA_DIR") or os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)


def _bbox(raw: str) -> tuple[float, float, float, float]:
    parts = [float(p) for p in raw.split(",")]
    if len(parts) != 4:
        raise ValueError("BBOX deve essere 'min_lon,min_lat,max_lon,max_lat'")
    return tuple(parts)  # type: ignore[return-value]


def _indirizzo(raw: str) -> str:
    """Aggiunge https:// se manca.

    Railway (come molti servizi) mostra il dominio senza schema, e copiarlo
    cosi' com'e' fa fallire il bot: Telegram accetta solo link https per le
    mini app. E' un errore quasi obbligatorio da fare, quindi si corregge qui
    invece di lasciarlo esplodere all'avvio.
    """
    raw = (raw or "").strip().rstrip("/")
    if not raw:
        return ""
    if raw.startswith(("http://", "https://")):
        return raw
    return "https://" + raw


def _url_database(data_dir: str) -> str:
    """Dove sta il database, con una rete di sicurezza contro il caso peggiore.

    Un percorso SQLite RELATIVO (sqlite:///./data/ndoma.db) dentro un
    container punta al filesystem dell'immagine, che a ogni deploy viene
    buttato via: e' il modo piu' facile di perdere gli iscritti senza
    accorgersene, perche' l'app riparte perfettamente, solo vuota. E' un
    errore quasi obbligatorio, perche' quel valore sta nel .env locale, dove
    e' giusto, e copiarlo nelle variabili del servizio sembra ovvio.

    Quindi: se DATA_DIR e' stato impostato di proposito - cioe' c'e' un
    volume - un percorso relativo viene spostato sul volume, dicendolo.
    Un percorso assoluto (quattro barre) o un database vero si rispettano
    cosi' come sono.
    """
    raw = (os.getenv("DATABASE_URL") or "").strip()
    if not raw:
        return f"sqlite:///{data_dir}/ndoma.db"
    if raw.startswith("sqlite:///") and not raw.startswith("sqlite:////"):
        percorso = raw[len("sqlite:///"):]
        if os.getenv("DATA_DIR") and not os.path.isabs(percorso):
            corretto = f"sqlite:///{data_dir}/{os.path.basename(percorso) or 'ndoma.db'}"
            # su stderr, MAI su stdout: gli script di avvio leggono lo
            # stdout di python per avere un numero, e un avviso stampato
            # li' dentro diventa parte del risultato. E' costato tre
            # passaggi saltati in silenzio a un deploy.
            print(f"ATTENZIONE: DATABASE_URL='{raw}' e' un percorso relativo e "
                  f"andrebbe perso a ogni deploy.\n"
                  f"            Con DATA_DIR impostato uso il volume: {corretto}",
                  file=sys.stderr)
            return corretto
    return raw


class Settings:
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    webapp_url: str = _indirizzo(os.getenv("WEBAPP_URL", "")) or "http://localhost:8000"
    telegram_group_id: str = os.getenv("TELEGRAM_GROUP_ID", "")

    # Giorno d'inverno da rigiocare, in formato AAAA-MM-GG. Se c'e', l'app
    # gira su dati reali di quel giorno invece che su quelli di oggi, e lo
    # dice in cima a ogni schermata. Vuoto = dati veri. Vedi app/simulazione.py
    simulazione_giorno: str = os.getenv("SIMULAZIONE_INVERNO", "")

    skitour_api_key: str = os.getenv("SKITOUR_API_KEY", "")
    ors_api_key: str = os.getenv("ORS_API_KEY", "")

    bbox = _bbox(os.getenv("BBOX", "6.55,44.00,7.95,44.75"))

    database_url: str = _url_database(DATA_DIR)
    # OpenTopoMap invece delle tile OSM standard: ha le curve di livello e
    # l'ombreggiatura del rilievo, e in montagna e' la differenza fra una
    # mappa che si legge e una macchia verde. Licenza CC-BY-SA, attribuzione
    # obbligatoria (quella qui sotto e' la formula che chiedono loro).
    # La loro politica d'uso ammette pochi download al secondo: per un
    # gruppo di amici va bene, per migliaia di utenti serve un servizio a
    # pagamento (MapTiler, Thunderforest) - si cambia solo questa variabile.
    tile_url: str = os.getenv(
        "TILE_URL", "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png")
    tile_attribution: str = os.getenv(
        "TILE_ATTRIBUTION",
        "Dati: &copy; OpenStreetMap contributors, SRTM | "
        "Stile: &copy; <a href=\"https://opentopomap.org\">OpenTopoMap</a> (CC-BY-SA)")
    user_agent: str = os.getenv("HTTP_USER_AGENT", "ndoma-a-skie/0.1")

    # File geografici scaricati da scripts/setup_geo.py
    comuni_geojson: str = os.path.join(DATA_DIR, "comuni.geojson")
    eaws_regions_geojson: str = os.path.join(DATA_DIR, "eaws_micro_regions.geojson")

    # Sorgenti (URL configurabili: se una cambia, si tocca solo qui)
    url_comuni_it: str = (
        "https://raw.githubusercontent.com/openpolis/geojson-italy/master/"
        "geojson/limits_IT_municipalities.geojson"
    )
    url_eaws_regions_tmpl: str = (
        "https://regions.avalanches.org/micro-regions/{regione}_micro-regions.geojson.json"
    )
    url_eaws_regions_latest_tmpl: str = (
        "https://regions.avalanches.org/micro-regions/latest/{regione}_micro-regions.geojson.json"
    )
    url_eaws_bulletins_dir: str = "https://static.avalanche.report/eaws_bulletins/{date}/"
    url_aineva_bulletin: str = "https://bollettini.aineva.it/bulletin/latest?province={province}"
    url_open_meteo: str = "https://api.open-meteo.com/v1/forecast"
    url_camptocamp: str = "https://api.camptocamp.org"
    url_skitour: str = "https://skitour.fr/api"
    url_overpass: str = "https://overpass-api.de/api/interpreter"
    url_ors_directions: str = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"
    # Quote lungo una linea, con la stessa chiave del routing. Accetta al
    # massimo 2000 vertici per richiesta: le tracce si semplificano prima
    # (vedi app/tracce.MAX_VERTICI).
    url_ors_elevation: str = "https://api.openrouteservice.org/elevation/line"
    # A piedi sui sentieri di OSM: serve solo per i PERCORSI CALCOLATI, che
    # non si mostrano sulle gite di sci. Vedi la nota in cima a app/tracce.py.
    url_ors_a_piedi: str = (
        "https://api.openrouteservice.org/v2/directions/foot-hiking/geojson")

    # Micro-regioni EAWS da caricare.
    # ATTENZIONE: l'Italia NON ha un file unico "IT", e' divisa per regione
    # amministrativa, perche' ogni regione emette il proprio bollettino:
    #   IT-21 Piemonte (ARPA Piemonte)   IT-23 Lombardia   IT-25 Veneto
    #   IT-32-BZ Bolzano   IT-32-TN Trento   IT-34 Friuli   IT-36 Emilia
    #   IT-57 Toscana      IT-MeteoMont (servizio nazionale dei Carabinieri)
    # La Francia invece ha un unico file "FR".
    # Per il Cuneese servono Piemonte e Francia.
    eaws_regioni = ["IT-21", "FR"]

    # Aree di Camptocamp da cui pescare gli itinerari.
    # L'API impagina con offset ma si ferma a 10000 (errore 400 oltre): senza
    # filtro per area l'elenco completo e' irraggiungibile. Filtrando per area
    # ogni insieme e' piccolo e si scorre tutto.
    # Per trovare l'id di un'altra area:
    #   https://api.camptocamp.org/search?q=NOME&t=a
    # Conviene mescolare confini amministrativi e catene montuose: un itinerario
    # a cavallo del confine puo' non essere associato alla provincia ma esserlo
    # al massiccio, e viceversa.
    camptocamp_aree = [
        280000,  # Provincia di Cuneo         (admin, ~400 itinerari)
        14360,   # Alpes-Maritimes            (admin, ~320)
        14362,   # Alpes-de-Haute-Provence    (admin: Ubaye, alta Tinee)
        14466,   # Mercantour - Argentera     (massiccio, entrambi i versanti)
        14432,   # Alpi Cozie - Queyras N     (massiccio: Maira, Varaita, Po)
    ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
