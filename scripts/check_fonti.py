"""Diagnosi delle fonti esterne: lancialo per primo, sul Mac.

Dice in trenta secondi quali endpoint rispondono, quali chiavi mancano e in
che formato arrivano i dati. Serve perche' i servizi a monte cambiano
(soprattutto i nomi dei file dei bollettini) e questo script te lo dice
subito invece di farti scoprire l'errore quando l'app e' gia' in mano agli amici.

  python scripts/check_fonti.py
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings  # noqa: E402

VERDE, ROSSO, GIALLO, FINE = "\033[92m", "\033[91m", "\033[93m", "\033[0m"


def esito(ok: bool | None, testo: str) -> None:
    simbolo = f"{VERDE}OK  {FINE}" if ok else (f"{GIALLO}?   {FINE}" if ok is None else f"{ROSSO}KO  {FINE}")
    print(f"  {simbolo} {testo}")


async def prova(c: httpx.AsyncClient, nome: str, url: str, **kw) -> httpx.Response | None:
    try:
        r = await c.get(url, **kw)
        esito(r.status_code == 200, f"{nome}: HTTP {r.status_code}  {url[:80]}")
        return r if r.status_code == 200 else None
    except Exception as e:
        esito(False, f"{nome}: {type(e).__name__} {e}")
        return None


async def principale() -> None:
    ua = {"User-Agent": settings.user_agent}
    async with httpx.AsyncClient(timeout=40, headers=ua, follow_redirects=True) as c:

        print("\n1) Meteo (Open-Meteo, nessuna chiave)")
        r = await prova(c, "open-meteo", settings.url_open_meteo, params={
            "latitude": 44.28, "longitude": 7.15,
            "hourly": "snowfall,temperature_2m,wind_speed_10m,freezing_level_height,snow_depth",
            "past_days": 3, "forecast_days": 5, "timezone": "Europe/Rome",
        })
        if r:
            h = r.json().get("hourly", {})
            esito(bool(h.get("snowfall")), f"variabili ricevute: {', '.join(list(h)[:6])}")
            r2 = await c.get(settings.url_open_meteo, params={
                "latitude": 44.28, "longitude": 7.15,
                "hourly": "wind_speed_700hPa", "forecast_days": 2})
            esito(r2.status_code == 200, "vento a 700 hPa (utile per il trasporto eolico)")

        print("\n2) Confini comunali ISTAT")
        r = await prova(c, "comuni", settings.url_comuni_it)
        if r:
            try:
                gj = r.json()
                n = len(gj.get("features", []))
                chiavi = list((gj["features"][0].get("properties") or {}).keys())[:8]
                esito(n > 7000, f"{n} comuni, proprieta': {chiavi}")
            except Exception as e:
                esito(False, f"json non interpretabile: {e}")

        print("\n3) Micro-regioni valanghe EAWS")
        for regione in settings.eaws_regioni:
            trovato = False
            for tmpl in (settings.url_eaws_regions_latest_tmpl, settings.url_eaws_regions_tmpl):
                rr = await prova(c, f"micro-regioni {regione}", tmpl.format(regione=regione))
                if rr:
                    trovato = True
                    break
            if not trovato:
                esito(False, f"nessuno schema di URL ha funzionato per {regione}: "
                             "l'Italia e' divisa per regione (IT-21 Piemonte, IT-23 Lombardia...), "
                             "controlla regions.avalanches.org e aggiorna eaws_regioni in config.py")

        print("\n4) Bollettini valanghe (archivio EAWS)")
        oggi = dt.date.today()
        trovato = False
        for delta in range(0, 8):
            g = oggi - dt.timedelta(days=delta)
            url = settings.url_eaws_bulletins_dir.format(date=g.isoformat())
            try:
                rr = await c.get(url)
            except Exception as e:
                esito(False, f"archivio non raggiungibile: {e}")
                break
            if rr.status_code == 200:
                import re
                nomi = re.findall(r'href="([^"?]+\.json)"', rr.text)
                if nomi:
                    trovato = True
                    it = [n for n in nomi if "IT" in n][:3]
                    fr = [n for n in nomi if "FR" in n][:3]
                    esito(True, f"{g}: {len(nomi)} file. Italia: {it or 'nessuno'} | Francia: {fr or 'nessuno'}")
                    break
        if not trovato:
            esito(None, "nessun bollettino negli ultimi 8 giorni: normale FUORI STAGIONE "
                        "(in Piemonte il bollettino e' sospeso d'estate). Riprova a dicembre.")
        await prova(c, "AINEVA (pagina pubblica)",
                    settings.url_aineva_bulletin.format(province="IT-21"))

        print("\n5) Camptocamp")
        r = await prova(c, "camptocamp", f"{settings.url_camptocamp}/routes",
                        params={"act": "skitouring", "limit": 3})
        if r:
            try:
                d = r.json()
                esito(True, f"{d.get('total', '?')} itinerari totali; "
                            f"campi: {list((d.get('documents') or [{}])[0].keys())[:8]}")
            except Exception as e:
                esito(False, f"json inatteso: {e}")

        print("\n6) Skitour.fr")
        if not settings.skitour_api_key:
            esito(None, "SKITOUR_API_KEY non impostata: registrati su skitour.fr e "
                        "copia la chiave dal tuo profilo")
        else:
            await prova(c, "skitour massifs", f"{settings.url_skitour}/massifs",
                        headers={**ua, "cle": settings.skitour_api_key})

        print("\n7) Overpass (OpenStreetMap)")
        await prova(c, "overpass", "https://overpass-api.de/api/status")

        print("\n8) openrouteservice")
        if not settings.ors_api_key:
            esito(None, "ORS_API_KEY non impostata: senza, il percorso viene "
                        "approssimato con una retta (nelle valli funziona comunque)")
        else:
            try:
                rr = await c.post(
                    settings.url_ors_directions,
                    json={"coordinates": [[7.55, 44.39], [7.05, 44.30]]},
                    headers={"Authorization": settings.ors_api_key,
                             "Content-Type": "application/json"},
                )
                esito(rr.status_code == 200, f"ORS directions: HTTP {rr.status_code}")
            except Exception as e:
                esito(False, f"ORS: {e}")

    print("\n9) Configurazione locale")
    esito(bool(settings.telegram_bot_token), "TELEGRAM_BOT_TOKEN")
    esito(settings.webapp_url.startswith("https"), f"WEBAPP_URL in https: {settings.webapp_url}")
    esito(os.path.exists(settings.comuni_geojson), "data/comuni.geojson (scripts/setup_geo.py)")
    esito(os.path.exists(settings.eaws_regions_geojson), "data/eaws_micro_regions.geojson")
    print()


if __name__ == "__main__":
    asyncio.run(principale())
