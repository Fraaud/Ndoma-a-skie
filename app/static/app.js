/* Ndoma a skié - mini app Telegram.
   Nessuna libreria oltre a Leaflet: sta tutto in un file, si legge in mezz'ora. */

const TG = window.Telegram?.WebApp;
let CONFIG = {};
let PROFILO = null;
let mappa = null;

if (TG) { TG.ready(); TG.expand(); }

/* ------------------------------------------------------------ utilita' */

async function api(percorso, opzioni = {}) {
  const headers = Object.assign(
    { "Content-Type": "application/json" },
    TG?.initData ? { "X-Telegram-Init-Data": TG.initData } : {},
    opzioni.headers || {}
  );
  /* Timeout esplicito: senza, una richiesta persa (segnale che va e viene,
     tunnel che cade) lascia l'interfaccia a girare per sempre. */
  const controllo = new AbortController();
  const scadenza = setTimeout(() => controllo.abort(), opzioni.timeout || 15000);
  let r;
  try {
    r = await fetch("/api" + percorso, Object.assign({}, opzioni, {
      headers, signal: opzioni.signal || controllo.signal,
    }));
  } catch (e) {
    if (e.name === "AbortError") {
      const err = new Error("il server non ha risposto entro 15 secondi");
      err.annullata = true;
      throw err;
    }
    throw new Error("server non raggiungibile (" + e.message + ")");
  } finally {
    clearTimeout(scadenza);
  }
  if (!r.ok) {
    let msg = "";
    try { msg = (await r.json()).detail || ""; } catch (e) {}
    throw new Error(`${r.status} ${msg || r.statusText}`);
  }
  return r.json();
}

/* Gli errori vanno SEMPRE mostrati nella pagina.
   TG.showAlert non e' affidabile: su alcune versioni di Telegram non fa
   nulla e l'utente vede un pulsante che non risponde, senza spiegazione.
   Lo usiamo solo in aggiunta, mai come unico canale. */
function avviso(idContenitore, testo, tipo = "errore") {
  const box = document.getElementById(idContenitore);
  if (!box) return;
  const colore = tipo === "ok" ? "" : "grave";
  box.innerHTML = testo ? `<div class="avviso ${colore}">${esc(testo)}</div>` : "";
  box.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function fuoriDaTelegram() {
  return !(TG && TG.initData);
}

/* Ricerca mentre si scrive: aspetta che l'utente si fermi e annulla la
   richiesta precedente. Senza, ogni lettera fa partire una chiamata e le
   risposte tornano in ordine sparso, sovrascrivendosi a vicenda. */
function ricercaLive(input, percorso, disegna, minimo = 2, attesa = 250) {
  let timer = null;
  let inCorso = null;
  input.addEventListener("input", () => {
    clearTimeout(timer);
    if (inCorso) { inCorso.abort(); inCorso = null; }
    const q = input.value.trim();
    if (q.length < minimo) { disegna(null); return; }
    timer = setTimeout(async () => {
      inCorso = new AbortController();
      try {
        disegna(await api(percorso(q), { signal: inCorso.signal }));
      } catch (e) {
        if (!e.annullata && e.name !== "AbortError") disegna(null, e);
      } finally {
        inCorso = null;
      }
    }, attesa);
  });
}

// gita aperta al momento, per passarla al modulo "ci vai?" senza rileggerla
let GITA_CORRENTE = null;

const BANNER_BROWSER = `<div class="avviso">
  Stai guardando dal browser, fuori da Telegram: puoi sfogliare le gite ma
  <b>non pubblicare</b>, perche' l'app non sa chi sei. Apri il bot su Telegram
  e usa il bottone "Apri Ndoma a skié".</div>`;

const el = document.getElementById("vista");
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, c => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function dataIt(iso) {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("it-IT", { weekday: "short", day: "2-digit", month: "short" });
}
function prossimoSabato() {
  const d = new Date();
  d.setDate(d.getDate() + ((6 - 1 - d.getDay() + 7) % 7 || (d.getDay() === 6 ? 0 : 7)));
  const s = new Date();
  s.setDate(s.getDate() + ((6 - s.getDay() + 7) % 7));
  return s.toISOString().slice(0, 10);
}
function fiocchi(n) {
  if (n === null || n === undefined) return "";
  const p = Math.round(n);
  return "❄".repeat(p) + '<span style="opacity:.22">' + "❄".repeat(5 - p) + "</span>";
}
function haptic() { try { TG?.HapticFeedback?.impactOccurred("light"); } catch (e) {} }

/* La mappa e' un di piu': se Leaflet non si carica (CDN irraggiungibile,
   segnale scarso in valle) il resto della scheda deve restare leggibile.
   Meteo e bollettino contano molto piu' della mappina. */
function mappaSicura(id, lat, lon, zoom = 12) {
  const box = document.getElementById(id);
  if (!box) return null;
  if (typeof L === "undefined") {
    box.style.height = "auto";
    box.innerHTML = `<div class="card" style="margin:0">
      <div class="hint">Mappa non disponibile (nessuna connessione alla mappa).</div>
      <a href="https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=13/${lat}/${lon}"
         target="_blank">Apri il punto su OpenStreetMap &rarr;</a></div>`;
    return null;
  }
  try {
    const mp = L.map(id, { scrollWheelZoom: false }).setView([lat, lon], zoom);
    L.tileLayer(CONFIG.tile_url, { attribution: CONFIG.tile_attribution, maxZoom: 17 }).addTo(mp);
    return mp;
  } catch (e) {
    box.innerHTML = `<div class="hint">Mappa non disponibile.</div>`;
    return null;
  }
}

/* ------------------------------------------------------------ router */

const VISTE = {};
let vistaCorrente = "weekend";

function vai(nome, arg) {
  vistaCorrente = nome;
  document.querySelectorAll("nav button").forEach(b =>
    b.classList.toggle("on", b.dataset.vista === nome));
  el.innerHTML = '<div class="carico">Carico...</div>';
  mappa = null;
  (VISTE[nome] || VISTE.weekend)(arg).catch(e => {
    el.innerHTML = `<div class="wrap"><div class="vuoto">Errore: ${esc(e.message)}</div></div>`;
  });
}
document.querySelectorAll("nav button").forEach(b =>
  b.addEventListener("click", () => { haptic(); vai(b.dataset.vista); }));

/* ------------------------------------------------------------ weekend */

VISTE.weekend = async function (giorno) {
  const g = giorno || prossimoSabato();
  const dom = new Date(g); dom.setDate(dom.getDate() + 1);
  const domenica = dom.toISOString().slice(0, 10);

  const dati = await api("/weekend?giorno=" + g);
  let h = `<div class="wrap"><h1>Dove ha nevicato</h1>
    <div class="hint" style="margin:-6px 0 12px">Centimetri misurati dal modello
    meteo e grado di pericolo ufficiale. Non e' una classifica di dove convenga
    andare: quella decisione non la fa l'app.</div>
    <div class="scelte" style="margin-bottom:14px">
      <button class="${g === prossimoSabato() ? "on" : ""}" onclick="vai('weekend','${prossimoSabato()}')">${dataIt(prossimoSabato())}</button>
      <button class="${g === domenica ? "on" : ""}" onclick="vai('weekend','${domenica}')">${dataIt(domenica)}</button>
    </div>`;

  if (!dati.risultati.length) {
    h += `<div class="vuoto">Nessun dato meteo ancora scaricato.<br><br>
      Lancia <code>python scripts/aggiorna.py</code> per popolare la cache,
      o importa il catalogo se e' vuoto.</div>`;
  }

  for (const r of dati.risultati) {
    const gr = r.valanghe_grado;
    h += `<div class="card click" onclick="vai('gita',{id:${r.gita.id},giorno:'${dati.giorno}'})">
      <div class="riga">
        <div style="min-width:0">
          <div class="titolo">${esc(r.gita.nome)}</div>
          <div class="meta">${esc(r.gita.valle || r.gita.comune || "")}
            ${r.gita.dislivello ? " &middot; " + r.gita.dislivello + " m D+" : ""}
            ${r.gita.difficolta ? " &middot; " + esc(r.gita.difficolta) : ""}</div>
        </div>
        <div class="center">
          <div class="neve-cm">${r.neve.ha_nevicato ? Math.round(r.neve.neve_72h_cm) + " cm" : "&mdash;"}</div>
          <div class="hint" style="font-size:10.5px">72h</div>
          ${gr ? `<div class="grado" style="justify-content:center;margin-top:6px">
            <span class="pallino g${gr}"></span>${gr}</div>` : ""}
        </div>
      </div>
      <div class="meta" style="margin-top:7px">${esc(r.neve.descrizione || "")}</div>
    </div>`;
  }
  if (dati.risultati.some(r => r.neve.ha_nevicato)) {
    h += `<div class="avviso grave">${esc(dati.avvertenza_neve || "")}</div>`;
  }
  h += `<div class="disclaimer">${esc(dati.disclaimer || "")}</div></div>`;
  el.innerHTML = h;
};

/* ------------------------------------------------------------ elenco gite */

VISTE.gite = async function () {
  const dati = await api("/gite?limite=200");
  const valli = await api("/valli");
  let h = `<div class="wrap"><h1>Catalogo</h1>
    <input id="cerca" placeholder="Cerca una gita o un comune..." autocomplete="off">
    <div style="margin-top:10px">
      <span class="tag" data-valle="">tutte (${dati.totale})</span>
      ${valli.map(v => `<span class="tag" data-valle="${esc(v.valle)}">${esc(v.valle)} (${v.gite})</span>`).join("")}
    </div>
    <div id="lista" class="sez"></div>
    <button class="secondario" style="width:100%;margin-top:16px" onclick="vai('nuovaGita')">
      + Aggiungi una gita che manca</button>
  </div>`;
  el.innerHTML = h;
  disegnaGite(dati.gite);

  // i nomi delle valli finiscono in un attributo, non dentro una stringa JS
  document.querySelectorAll(".tag[data-valle]").forEach(t =>
    t.addEventListener("click", async () => {
      const d = await api("/gite?limite=200&valle=" + encodeURIComponent(t.dataset.valle));
      disegnaGite(d.gite);
    }));

  const cerca = document.getElementById("cerca");
  ricercaLive(cerca, q => "/gite?limite=60&q=" + encodeURIComponent(q), async (d, errore) => {
    if (errore) { disegnaGite([]); return; }
    if (d) { disegnaGite(d.gite); return; }
    disegnaGite((await api("/gite?limite=200")).gite);   // campo svuotato
  });
};

function disegnaGite(gite) {
  const lista = document.getElementById("lista");
  if (!lista) return;
  if (!gite.length) { lista.innerHTML = '<div class="vuoto">Nessuna gita.</div>'; return; }
  lista.innerHTML = gite.map(g => `
    <div class="card click" onclick="vai('gita',${g.id})">
      <div class="titolo">${esc(g.nome)}</div>
      <div class="meta">${esc(g.comune || "")}${g.valle ? " &middot; " + esc(g.valle) : ""}
        ${g.dislivello ? " &middot; " + g.dislivello + " m D+" : ""}
        ${g.difficolta ? " &middot; " + esc(g.difficolta) : ""}</div>
    </div>`).join("");
}

/* ------------------------------------------------------------ scheda gita */

VISTE.gita = async function (arg) {
  const id = typeof arg === "object" ? arg.id : arg;
  const giorno = (typeof arg === "object" && arg.giorno) ? arg.giorno : null;
  const s = await api("/gite/" + id + (giorno ? "?giorno=" + giorno : ""));
  const g = s.gita, n = s.neve || {}, v = s.valanghe || {}, m = s.meteo || {};

  /* selettore del giorno: la qualita' della neve cambia da un giorno all'altro,
     quindi la scheda deve poter essere letta per il giorno in cui si va */
  const oggi = new Date();
  const giorni = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(oggi); d.setDate(d.getDate() + i);
    return d.toISOString().slice(0, 10);
  });

  let h = `<div class="wrap">
    <button class="torna" onclick="vai('gite')">&larr; catalogo</button>
    <h1>${esc(g.nome)}</h1>
    <div class="meta" style="margin:-8px 0 12px">${esc(g.comune || "")}
      ${g.valle ? " &middot; " + esc(g.valle) : ""}</div>
    <div id="mappa"></div>
    <div class="giorni" style="margin-bottom:12px">
      ${giorni.map(d => `<div class="giorno" style="cursor:pointer;
        ${d === s.giorno ? "outline:2px solid var(--btn)" : ""}"
        onclick="vai('gita',{id:${g.id},giorno:'${d}'})">
        <b>${dataIt(d).split(" ")[0]}</b>${dataIt(d).split(" ").slice(1).join(" ")}</div>`).join("")}
    </div>
    <div>
      ${g.quota_min ? `<span class="tag">attacco ${g.quota_min} m</span>` : ""}
      ${g.quota_max ? `<span class="tag">cima ${g.quota_max} m</span>` : ""}
      ${g.dislivello ? `<span class="tag">${g.dislivello} m D+</span>` : ""}
      ${g.esposizione ? `<span class="tag">esp. ${esc(g.esposizione)}</span>` : ""}
      ${g.difficolta ? `<span class="tag">${esc(g.difficolta)}</span>` : ""}
    </div>`;

  /* --- neve --- */
  if (n.disponibile) {
    h += `<h2>Neve caduta</h2>
    <div class="powder-box">
      <div class="riga">
        <div>
          <div class="powder-num">${n.ha_nevicato ? Math.round(n.neve_72h_cm) + " cm" : "niente"}</div>
          <div class="hint">${n.ha_nevicato ? "nelle ultime 72 ore" : "nelle ultime 72 ore"}</div>
        </div>
      </div>
      <div class="meta" style="margin-top:8px">${esc(n.descrizione || "")}</div>
    </div>`;
    if (n.avvertenza) {
      h += `<div class="avviso grave">${esc(n.avvertenza)}</div>`;
    }
  }

  /* --- valanghe: si riporta, non si valuta --- */
  h += `<h2>Pericolo valanghe</h2>`;
  if (v.non_disponibile) {
    h += `<div class="card"><div class="hint">Bollettino non disponibile qui
      (fuori stagione o regione non coperta).</div>
      <a href="${v.link_ufficiale}" target="_blank" style="display:inline-block;margin-top:8px">
      Apri il bollettino ufficiale &rarr;</a></div>`;
  } else {
    const gr = v.grado_massimo;
    h += `<div class="card">
      <div class="grado"><span class="pallino g${gr || 0}"></span>
        Grado ${gr || "-"} ${esc((v.gradi?.[0]?.testo) || "")}</div>
      ${v.problemi?.length ? `<div style="margin-top:9px">
        <div class="hint" style="margin-bottom:4px">Problemi segnalati dal bollettino:</div>
        ${v.problemi.map(pr => `<div class="meta" style="margin:3px 0">&bull;
          <b>${esc(pr.tipo_it)}</b>${pr.esposizioni.length ? " &mdash; esposizioni " + pr.esposizioni.join("-") : ""}${pr.quota_min ? ", sopra " + pr.quota_min + " m" : ""}${pr.quota_max ? ", sotto " + pr.quota_max + " m" : ""}</div>`).join("")}
      </div>` : ""}
      ${v.sintesi ? `<div class="meta" style="margin-top:9px">${esc(v.sintesi)}</div>` : ""}
      <div class="hint" style="margin-top:9px;font-size:11.5px">
        ${v.ente ? esc(v.ente) + " &middot; " : ""}${v.emesso_il ? "emesso " + esc(String(v.emesso_il).slice(0, 16).replace("T", " ")) : ""}</div>
      <a href="${v.link_ufficiale}" target="_blank"
        style="display:inline-block;margin-top:8px">Bollettino integrale &rarr;</a>
    </div>`;
    h += `<div class="avviso">Questo e' un estratto. <b>Il bollettino va letto
      per intero prima di uscire</b>: l'app non dice quali problemi riguardino
      questa gita, e non e' in grado di dirlo.</div>`;
  }

  /* --- previsione --- */
  if (s.previsione_giorni?.length) {
    h += `<h2>Prossimi giorni</h2><div class="giorni">` +
      s.previsione_giorni.map(d => `<div class="giorno">
        <b>${dataIt(d.giorno).split(" ")[0]}</b>
        ${d.temp_min !== null && d.temp_min !== undefined ? Math.round(d.temp_min) + "&deg;/" + Math.round(d.temp_max) + "&deg;" : "-"}
        <div class="neve">${d.neve_prevista_cm ? Math.round(d.neve_prevista_cm) + " cm" : "&mdash;"}</div>
        <div class="hint" style="font-size:10.5px">${d.quota_zero ? "0&deg; " + Math.round(d.quota_zero) + "m" : ""}</div>
      </div>`).join("") + `</div>`;
  }

  /* --- azioni --- */
  // il nome passa per una variabile, non interpolato nell'HTML: gite come
  // "Punta Colombo da Sant'Anna" romperebbero la stringa JavaScript
  GITA_CORRENTE = { id: g.id, nome: g.nome };
  const apri = (t) =>
    `vai('nuovaUscita',{gita:GITA_CORRENTE.id,nome:GITA_CORRENTE.nome,tipo:'${t}'})`;
  h += `<h2>Ci vai?</h2>
    <div class="scelte">
      <button onclick="${apri("OFFRO")}">Offro posti</button>
      <button onclick="${apri("CERCO")}">Cerco passaggio</button>
      <button onclick="${apri("COMPAGNI")}">Cerco compagnia</button>
    </div>`;

  if (g.fonte_url) {
    h += `<div class="disclaimer" style="margin-top:18px">
      Dati dell'itinerario da <a href="${g.fonte_url}" target="_blank">${esc(g.fonte)}</a>
      ${g.licenza ? " (" + esc(g.licenza) + ")" : ""}${g.autori ? " &mdash; " + esc(g.autori) : ""}.
      La relazione completa e la descrizione dell'avvicinamento si leggono sulla fonte.</div>`;
  }
  h += `<div class="disclaimer">${esc(s.disclaimer || "")}</div></div>`;
  el.innerHTML = h;

  const mp = mappaSicura("mappa", g.lat, g.lon, 12);
  if (mp) { L.marker([g.lat, g.lon]).addTo(mp).bindPopup("Attacco / parcheggio"); mappa = mp; }
};

/* ------------------------------------------------------------ passaggi */

VISTE.passaggi = async function () {
  const uscite = await api("/uscite");
  let h = `<div class="wrap"><h1>Passaggi</h1>
    <div class="scelte" style="margin-bottom:6px">
      <button onclick="vai('nuovaUscita',{tipo:'OFFRO'})">Offro</button>
      <button onclick="vai('nuovaUscita',{tipo:'CERCO'})">Cerco</button>
      <button onclick="vai('nuovaUscita',{tipo:'COMPAGNI'})">Compagnia</button>
    </div>`;
  if (!uscite.length) {
    h += `<div class="vuoto">Ancora nessuna uscita nei prossimi giorni.<br>
      Rompi il ghiaccio: pubblica la tua.</div>`;
  }
  let ultimaData = "";
  for (const u of uscite) {
    if (u.data !== ultimaData) { h += `<h2>${dataIt(u.data)}</h2>`; ultimaData = u.data; }
    h += `<div class="card">
      <div class="riga">
        <div style="min-width:0">
          <span class="badge-tipo t-${u.tipo}">${u.tipo}</span>
          <div class="titolo" style="margin-top:6px">${esc(u.gita?.nome || u.zona || "zona da definire")}</div>
          <div class="meta">da ${esc(u.comune_partenza || "?")}
            ${u.ora_partenza ? " &middot; " + esc(u.ora_partenza) : ""}
            ${u.tipo === "OFFRO" ? " &middot; " + u.posti + " posti" : ""}</div>
          ${u.note ? `<div class="meta">${esc(u.note)}</div>` : ""}
        </div>
        ${u.autore?.username
          ? `<a class="secondario" style="text-decoration:none;white-space:nowrap"
               href="https://t.me/${esc(u.autore.username)}" target="_blank">scrivi</a>`
          : ""}
      </div>
    </div>`;
  }
  h += `</div>`;
  el.innerHTML = h;
};

/* ------------------------------------------------------- nuova uscita */

VISTE.nuovaUscita = async function (opz = {}) {
  const oggi = new Date().toISOString().slice(0, 10);
  const tipo = opz.tipo || "OFFRO";

  el.innerHTML = `<div class="wrap">
    <button class="torna" onclick="vai('passaggi')">&larr; passaggi</button>
    <h1>Nuova uscita</h1>
    ${fuoriDaTelegram() ? BANNER_BROWSER : ""}

    <label>Cosa fai</label>
    <div class="scelte" id="tipi">
      <button data-t="OFFRO">Offro posti</button>
      <button data-t="CERCO">Cerco passaggio</button>
      <button data-t="COMPAGNI">Cerco compagnia</button>
    </div>

    <label>Gita</label>
    <input id="cercaGita" placeholder="Scrivi il nome della gita..." autocomplete="off"
      value="${esc(opz.nome || "")}">
    <input type="hidden" id="gitaId" value="${opz.gita || ""}">
    <div id="suggGita" class="suggerimenti" style="display:none"></div>
    <div id="gitaScelta" class="hint" style="margin-top:6px"></div>

    <div id="zonaBox" style="display:none">
      <label>Zona (se la gita non e' decisa)</label>
      <input id="zona" placeholder="es. Valle Stura, Marittime...">
    </div>

    <label>Giorno</label>
    <input type="date" id="data" value="${prossimoSabato()}" min="${oggi}">

    <label>Flessibilita'</label>
    <select id="flex">
      <option value="0">quel giorno preciso</option>
      <option value="1">&plusmn; 1 giorno</option>
      <option value="2">&plusmn; 2 giorni</option>
      <option value="3">tutto il weekend</option>
    </select>

    <label>Ora di partenza</label>
    <input type="time" id="ora" value="05:30">

    <label>Parto da</label>
    <input id="comune" placeholder="comune..." autocomplete="off"
      value="${esc(PROFILO?.comune_partenza || "")}">
    <input type="hidden" id="istat" value="${esc(PROFILO?.istat_partenza || "")}">
    <div id="sugg" class="suggerimenti" style="display:none"></div>

    <div id="postiBox">
      <label>Posti disponibili</label>
      <input type="number" id="posti" min="0" max="8" value="${PROFILO?.posti_default ?? 3}">
    </div>

    <label>Note</label>
    <textarea id="note" placeholder="Es. rientro entro le 17, ho il portasci, si divide la benzina"></textarea>

    <div id="stato"></div>
    <button class="primario" id="salva">Pubblica</button>
  </div>`;

  let tipoScelto = tipo;
  const aggiornaTipo = () => {
    document.querySelectorAll("#tipi button").forEach(b =>
      b.classList.toggle("on", b.dataset.t === tipoScelto));
    document.getElementById("postiBox").style.display = tipoScelto === "OFFRO" ? "" : "none";
  };
  document.querySelectorAll("#tipi button").forEach(b =>
    b.addEventListener("click", () => { tipoScelto = b.dataset.t; haptic(); aggiornaTipo(); }));
  aggiornaTipo();

  /* scelta della gita: si cerca invece di scorrere un elenco di 500 voci */
  const inpGita = document.getElementById("cercaGita");
  const suggGita = document.getElementById("suggGita");
  const campoGitaId = document.getElementById("gitaId");
  const scelta = document.getElementById("gitaScelta");

  const aggiornaZona = () => {
    document.getElementById("zonaBox").style.display = campoGitaId.value ? "none" : "";
    scelta.textContent = campoGitaId.value
      ? "Gita scelta. Svuota il campo per lasciarla da decidere."
      : "Nessuna gita scelta: indica almeno la zona qui sotto.";
  };
  aggiornaZona();

  inpGita.addEventListener("input", () => {   // scrivere annulla la scelta
    campoGitaId.value = "";
    aggiornaZona();
  });

  ricercaLive(inpGita, q => "/gite?limite=12&q=" + encodeURIComponent(q), (dati) => {
    if (!dati || !dati.gite.length) { suggGita.style.display = "none"; return; }
    suggGita.innerHTML = dati.gite.map(g =>
      `<div data-id="${g.id}" data-nome="${esc(g.nome)}">${esc(g.nome)}
        <span class="hint">${esc(g.valle || g.comune || "")}</span></div>`).join("");
    suggGita.style.display = "";
    suggGita.querySelectorAll("div[data-id]").forEach(d => d.addEventListener("click", () => {
      inpGita.value = d.dataset.nome;
      campoGitaId.value = d.dataset.id;
      suggGita.style.display = "none";
      aggiornaZona();
    }));
  });

  /* autocomplete comuni */
  const inpComune = document.getElementById("comune");
  const sugg = document.getElementById("sugg");
  ricercaLive(inpComune, q => "/comuni?q=" + encodeURIComponent(q), (res) => {
    if (!res || !res.length) { sugg.style.display = "none"; return; }
    sugg.innerHTML = res.map(c =>
      `<div data-istat="${c.istat}" data-nome="${esc(c.nome)}">${esc(c.nome)}
        <span class="hint">${esc(c.provincia || "")}</span></div>`).join("");
    sugg.style.display = "";
    sugg.querySelectorAll("div[data-istat]").forEach(d => d.addEventListener("click", () => {
      inpComune.value = d.dataset.nome;
      document.getElementById("istat").value = d.dataset.istat;
      sugg.style.display = "none";
    }));
  });

  const bottone = document.getElementById("salva");
  bottone.addEventListener("click", async () => {
    if (fuoriDaTelegram()) {
      avviso("stato", "Per pubblicare devi aprire l'app da Telegram.");
      return;
    }
    const corpo = {
      tipo: tipoScelto,
      gita_id: campoGitaId.value ? Number(campoGitaId.value) : null,
      zona: document.getElementById("zona")?.value || null,
      data: document.getElementById("data").value,
      flessibilita: Number(document.getElementById("flex").value),
      ora_partenza: document.getElementById("ora").value || null,
      istat_partenza: document.getElementById("istat").value || null,
      posti: Number(document.getElementById("posti")?.value || 1),
      note: document.getElementById("note").value || null,
    };
    if (!corpo.data) { avviso("stato", "Scegli il giorno."); return; }
    if (!corpo.gita_id && !corpo.zona) {
      avviso("stato", "Scegli una gita, oppure scrivi almeno la zona.");
      return;
    }

    bottone.disabled = true;
    bottone.textContent = "Pubblico...";
    avviso("stato", "");
    try {
      await api("/uscite", { method: "POST", body: JSON.stringify(corpo) });
      haptic();
      try { TG?.showAlert?.("Pubblicata. Ti avviso appena arriva un match."); } catch (e) {}
      vai("profilo");
    } catch (e) {
      // l'errore si vede nella pagina: showAlert su alcune versioni di
      // Telegram non fa nulla e l'utente resta senza spiegazione
      avviso("stato", "Non sono riuscito a pubblicare: " + e.message);
      bottone.disabled = false;
      bottone.textContent = "Pubblica";
    }
  });
};

/* -------------------------------------------------------- nuova gita */

VISTE.nuovaGita = async function () {
  el.innerHTML = `<div class="wrap">
    <button class="torna" onclick="vai('gite')">&larr; catalogo</button>
    <h1>Aggiungi una gita</h1>
    <div class="hint">Metti il punto dove si parcheggia: e' la coordinata che serve
      per meteo, valanghe e per calcolare chi ti passa vicino.</div>
    <div id="mappa" style="height:260px;margin-top:12px"></div>
    <label>Nome</label><input id="nome" placeholder="es. Testa Malacosta da Pontebernardo">
    <label>Zona / valle</label><input id="valle" placeholder="es. Valle Stura">
    <div style="display:flex;gap:10px">
      <div style="flex:1"><label>Quota attacco</label><input type="number" id="qmin" placeholder="1300"></div>
      <div style="flex:1"><label>Quota cima</label><input type="number" id="qmax" placeholder="2850"></div>
    </div>
    <div style="display:flex;gap:10px">
      <div style="flex:1"><label>Esposizione</label><input id="esp" placeholder="N, NE"></div>
      <div style="flex:1"><label>Difficolta'</label><input id="dif" placeholder="BSA / 3.1"></div>
    </div>
    <button class="primario" id="salva">Salva</button>
    <div class="disclaimer">Non copiare testi o relazioni da altri siti: qui servono
      solo i dati e la posizione. Per la relazione si linka la fonte.</div>
  </div>`;

  const centro = [(CONFIG.bbox[1] + CONFIG.bbox[3]) / 2, (CONFIG.bbox[0] + CONFIG.bbox[2]) / 2];
  const mp = mappaSicura("mappa", centro[0], centro[1], 10);
  let marker = null;
  if (mp) {
    mp.on("click", (e) => {
      if (marker) mp.removeLayer(marker);
      marker = L.marker(e.latlng).addTo(mp);
    });
  } else {
    // senza mappa si inseriscono le coordinate a mano: meglio che bloccare tutto
    document.getElementById("mappa").insertAdjacentHTML("afterend", `
      <div style="display:flex;gap:10px">
        <div style="flex:1"><label>Latitudine</label>
          <input id="latM" type="number" step="0.00001" placeholder="44.32"></div>
        <div style="flex:1"><label>Longitudine</label>
          <input id="lonM" type="number" step="0.00001" placeholder="7.03"></div>
      </div>`);
  }

  document.getElementById("salva").addEventListener("click", async () => {
    const latM = Number(document.getElementById("latM")?.value);
    const lonM = Number(document.getElementById("lonM")?.value);
    const punto = marker ? { lat: marker.getLatLng().lat, lon: marker.getLatLng().lng }
                         : (latM && lonM ? { lat: latM, lon: lonM } : null);
    if (!punto) {
      const msg = "Indica il punto del parcheggio sulla mappa (o scrivi le coordinate).";
      TG?.showAlert ? TG.showAlert(msg) : alert(msg);
      return;
    }
    const corpo = {
      nome: document.getElementById("nome").value,
      lat: punto.lat, lon: punto.lon,
      quota_min: Number(document.getElementById("qmin").value) || null,
      quota_max: Number(document.getElementById("qmax").value) || null,
      esposizione: document.getElementById("esp").value || null,
      difficolta: document.getElementById("dif").value || null,
      valle: document.getElementById("valle").value || null,
    };
    try {
      const g = await api("/gite", { method: "POST", body: JSON.stringify(corpo) });
      vai("gita", g.id);
    } catch (e) {
      TG?.showAlert ? TG.showAlert("Errore: " + e.message) : alert(e.message);
    }
  });
};

/* ------------------------------------------------------------ profilo */

VISTE.profilo = async function () {
  PROFILO = await api("/profilo");
  const mie = await api("/mie");

  let h = `<div class="wrap"><h1>Profilo</h1>
    <div class="hint">Le preferenze si salvano una volta: dopo, pubblicare
      un'uscita sono due tap.</div>
    <label>Parto abitualmente da</label>
    <input id="comune" autocomplete="off" value="${esc(PROFILO.comune_partenza || "")}">
    <input type="hidden" id="istat" value="${esc(PROFILO.istat_partenza || "")}">
    <div id="sugg" class="suggerimenti" style="display:none"></div>
    <label>Ho l'auto</label>
    <select id="auto">
      <option value="1" ${PROFILO.ha_auto ? "selected" : ""}>si'</option>
      <option value="0" ${!PROFILO.ha_auto ? "selected" : ""}>no</option>
    </select>
    <label>Posti che offro di solito</label>
    <input type="number" id="posti" min="0" max="8" value="${PROFILO.posti_default}">
    <label>Notifiche dei match</label>
    <select id="notif">
      <option value="1" ${PROFILO.notifiche ? "selected" : ""}>attive</option>
      <option value="0" ${!PROFILO.notifiche ? "selected" : ""}>disattivate</option>
    </select>
    <button class="primario" id="salva">Salva</button>`;

  h += `<h2>Le mie uscite</h2>`;
  if (!mie.length) h += `<div class="hint">Nessuna uscita pubblicata.</div>`;
  for (const u of mie) {
    h += `<div class="card">
      <span class="badge-tipo t-${u.tipo}">${u.tipo}</span>
      <div class="titolo" style="margin-top:6px">${esc(u.gita?.nome || u.zona || "")}</div>
      <div class="meta">${dataIt(u.data)} &middot; ${esc(u.stato)}</div>
      ${(u.match || []).map(m => `<div class="match">
        <b>${esc(m.uscita.autore?.nome || "qualcuno")}</b>
        ${m.uscita.autore?.username ? `<a href="https://t.me/${esc(m.uscita.autore.username)}" target="_blank">@${esc(m.uscita.autore.username)}</a>` : ""}
        <span class="badge-tipo t-${m.uscita.tipo}">${m.uscita.tipo}</span>
        <div class="meta">${esc(m.motivo)}</div></div>`).join("")}
      ${u.stato === "aperta" ? `<button class="secondario" style="margin-top:10px"
        onclick="chiudi(${u.id})">Chiudi</button>` : ""}
    </div>`;
  }
  h += `</div>`;
  el.innerHTML = h;

  const inp = document.getElementById("comune"), sugg = document.getElementById("sugg");
  ricercaLive(inp, q => "/comuni?q=" + encodeURIComponent(q), (res) => {
    if (!res || !res.length) { sugg.style.display = "none"; return; }
    sugg.innerHTML = res.map(c => `<div data-istat="${c.istat}" data-nome="${esc(c.nome)}">
      ${esc(c.nome)} <span class="hint">${esc(c.provincia || "")}</span></div>`).join("");
    sugg.style.display = "";
    sugg.querySelectorAll("div[data-istat]").forEach(d => d.addEventListener("click", () => {
      inp.value = d.dataset.nome;
      document.getElementById("istat").value = d.dataset.istat;
      sugg.style.display = "none";
    }));
  });

  document.getElementById("salva").addEventListener("click", async () => {
    await api("/profilo", {
      method: "PUT",
      body: JSON.stringify({
        comune_partenza: inp.value || null,
        istat_partenza: document.getElementById("istat").value || null,
        ha_auto: document.getElementById("auto").value === "1",
        posti_default: Number(document.getElementById("posti").value),
        notifiche: document.getElementById("notif").value === "1",
      }),
    });
    haptic();
    TG?.showAlert ? TG.showAlert("Salvato.") : alert("Salvato.");
  });
};

window.chiudi = async function (id) {
  await api("/uscite/" + id + "/chiudi", { method: "POST" });
  vai("profilo");
};
window.vai = vai;

/* ------------------------------------------------------------ avvio */

(async function () {
  try {
    CONFIG = await api("/config");
    try { PROFILO = await api("/profilo"); } catch (e) { /* fuori da Telegram */ }
    vai("weekend");
  } catch (e) {
    el.innerHTML = `<div class="wrap"><div class="vuoto">
      Non riesco a contattare il server.<br>${esc(e.message)}</div></div>`;
  }
})();
