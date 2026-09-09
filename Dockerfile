# Immagine per Railway: tutte le dipendenze installate a livello di sistema.
#
# Perche' Docker e non Nixpacks: Nixpacks mette le librerie in un virtualenv
# (/opt/venv) che la shell del servizio NON attiva. Aprire la shell e lanciare
# "python scripts/importa.py" finiva quindi in ModuleNotFoundError. Qui python
# e' uno solo e le librerie ci sono sempre, dalla shell come dall'avvio.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data

WORKDIR /app

# ca-certificates: servono per parlare in https con open-meteo, camptocamp e
# avalanche.report.  tzdata: il promemoria del giovedi' alle 19:00 deve cadere
# a un'ora sensata.  curl: comodo per una prova al volo dalla shell.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates tzdata curl \
 && rm -rf /var/lib/apt/lists/*

# Prima le dipendenze, poi il codice: cosi' Docker rifa' il "pip install" solo
# quando cambia requirements.txt, e i deploy successivi durano pochi secondi.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Se il volume non e' montato la cartella deve comunque esistere: l'app parte
# lo stesso, semplicemente i dati non sopravvivono al riavvio.
RUN mkdir -p /data

EXPOSE 8000
CMD ["bash", "deploy/avvio_railway.sh"]
