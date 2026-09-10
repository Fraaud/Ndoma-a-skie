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

/* Posizione GPS e sorveglianza attiva: stanno qui in cima, e non accanto
   alla schermata Emergenza che le usa, perche' il router le azzera quando
   si cambia vista - e una variabile dichiarata dopo chi la legge e' una
   trappola che aspetta soltanto il giorno in cui qualcuno sposta una
   funzione. */
let POSIZIONE = null;
let SORVEGLIANZA = null;

const BANNER_BROWSER = `<div class="avviso">
  Stai guardando dal browser, fuori da Telegram: puoi sfogliare le gite ma
  <b>non pubblicare</b>, perche' l'app non sa chi sei. Apri il bot su Telegram
  e usa il bottone "Apri Ndoma a skié".</div>`;

const el = document.getElementById("vista");
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, c => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* Un campo lasciato vuoto vale null, non stringa vuota: sul server "non
   dichiarato" e' un'informazione, "" sarebbe una risposta sbagliata. */
const valore = (id) => (document.getElementById(id)?.value || "") || null;
const valoreNumero = (id) => {
  const v = document.getElementById(id)?.value;
  return v === "" || v === undefined || v === null ? null : Number(v);
};

/* L'esperienza dichiarata, sotto il nome di chi ha pubblicato. Chi non ha
   dichiarato niente si vede lo stesso, in grigio: e' un'informazione. */
function rigaEsperienza(autore) {
  const t = autore?.esperienza;
  if (!t) return "";
  const assente = t === "esperienza non dichiarata";
  return `<div class="esperienza${assente ? " assente" : ""}">${esc(t)}</div>`;
}

/* La freccetta a destra delle righe toccabili. Non e' decorazione: e' il
   segno con cui su un telefono si capisce che una riga si apre. */
const FRECCIA = `<svg class="freccia" viewBox="0 0 8 14"><path d="M1 1l6 6-6 6"/></svg>`;

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

/* Quanto ci metti ad arrivare all'attacco, e che paesi attraversi.

   E' lo stesso percorso stradale che serve al match: "quanto ci metto?" e
   "chi passa da casa mia?" sono la stessa domanda vista da due lati. La
   prima volta il server risponde "in_calcolo" (interseca il percorso con
   867 poligoni comunali, non e' istantaneo) e si richiede una volta sola,
   dopo qualche secondo: se non e' pronto neanche allora, pazienza, si
   ripresenta aprendo di nuovo la scheda. */
async function disegnaAvvicinamento(gitaId, riprova = true) {
  const box = document.getElementById("avvicinamento");
  if (!box || fuoriDaTelegram()) return;
  let d;
  try {
    d = await api("/avvicinamento/" + gitaId);
  } catch (e) {
    return;   // e' un di piu': se non arriva, la scheda resta completa
  }
  if (!box.isConnected) return;   // l'utente ha già cambiato schermata

  if (d.stato === "senza_comune") {
    box.innerHTML = `<div class="card" style="margin-top:12px">
      <div class="hint">Dì da dove parti abitualmente e ti dico quanto ci
      metti ad arrivare, e da quali paesi passi.</div>
      <button class="secondario" style="margin-top:8px"
        onclick="vai('profilo')">Imposta il comune di partenza</button></div>`;
    return;
  }
  if (d.stato === "in_calcolo") {
    box.innerHTML = `<div class="card" style="margin-top:12px">
      <div class="hint">Sto calcolando il percorso da casa tua...</div></div>`;
    if (riprova) setTimeout(() => disegnaAvvicinamento(gitaId, false), 4000);
    return;
  }

  const paesi = d.comuni || [];
  box.innerHTML = `<h2>Da ${esc(d.da || "casa tua")}</h2>
    <div class="card">
      ${d.minuti ? `<div class="riga">
        <div><div class="powder-num">${d.minuti} min</div>
          <div class="hint">di auto${d.km ? ", " + d.km + " km" : ""}</div></div>
      </div>` : `<div class="hint">Tempo di percorrenza non disponibile:
        manca la chiave di routing (ORS_API_KEY), quindi il percorso e' una
        retta e i paesi qui sotto sono un'approssimazione.</div>`}
      ${paesi.length ? `<div style="margin-top:10px">
        <div class="hint" style="margin-bottom:4px">Passi da:</div>
        <div>${paesi.map(n => `<span class="tag">${esc(n)}</span>`).join("")}</div>
        <div class="hint" style="margin-top:8px;font-size:11.5px">Chi abita in
          uno di questi paesi e' sulla tua strada: e' cosi' che l'app trova i
          passaggi.</div></div>` : ""}
    </div>`;

  disegnaPiole(d.piole || []);
}

/* Le piole lungo la strada di casa.

   Il filtro non e' "vicino all'attacco" ma "lungo il corridoio del
   ritorno": alle cinque di sera, a 1600 m, non c'e' niente di aperto - la
   piola dove ci si ferma e' in fondovalle. E' lo stesso corridoio che serve
   ai passaggi in auto, letto al contrario. */
function disegnaPiole(piole) {
  const box = document.getElementById("piole");
  if (!box || !box.isConnected) return;
  if (!piole.length) { box.innerHTML = ""; return; }

  box.innerHTML = `<h2>Dopo la gita</h2>
    <div class="gruppo">
      ${piole.map(p => `<div class="voce" style="cursor:default">
        <div class="corpo">
          <div class="titolo" style="font-size:15.5px">${esc(p.etichetta)}</div>
          <div class="meta">${esc(p.genere || "")}${p.comune ? " &middot; " + esc(p.comune) : ""}</div>
        </div>
        ${p.dettagli?.phone ? `<a class="secondario" style="text-decoration:none"
          href="tel:${esc(String(p.dettagli.phone).replace(/[^+\d]/g, ""))}">chiama</a>` : ""}
      </div>`).join("")}
    </div>
    <div class="hint" style="padding:0 var(--lato)">Sulla strada di casa, nei
      paesi che attraversi. Da OpenStreetMap: <b>gli orari non li mostriamo</b>
      perche' in valle sono vecchi di anni &mdash; meglio una telefonata.</div>`;
}

/* Parcheggi e ripari all'attacco.

   La capienza del parcheggio e' il dato piu' nostro che esista: l'app e'
   nata da sei macchine ferme in un piazzale. Nessun'altra app la mostra,
   e OpenStreetMap ce l'ha.

   I ripari si scaricano qui anche se nessuno li ha chiesti, e si tengono da
   parte per la schermata Emergenza: quando serviranno, in valle, il
   telefono sara' probabilmente senza campo. */
async function disegnaPosti(gita, tramonto) {
  const box = document.getElementById("posti");
  if (!box) return;
  let d;
  try {
    d = await api("/posti/" + gita.id);
  } catch (e) {
    box.innerHTML = "";
    return;
  }
  if (!box.isConnected) return;
  ricordaPerEmergenza(gita, d.ripari || [], tramonto);

  const parcheggi = d.parcheggi || [];
  let h = "";
  if (parcheggi.length) {
    h += `<h2>Al parcheggio</h2><div class="gruppo">`;
    for (const p of parcheggi) {
      const posti = p.capienza !== null && p.capienza !== undefined;
      h += `<div class="voce" style="cursor:default">
        <div class="corpo">
          <div class="titolo" style="font-size:15.5px">${esc(p.etichetta)}</div>
          <div class="meta">${p.distanza_m < 1000
            ? p.distanza_m + " m dall'attacco" : p.distanza_km + " km dall'attacco"}
            ${p.quota ? " &middot; " + p.quota + " m" : ""}
            ${p.dettagli?.fee === "yes" ? " &middot; a pagamento" : ""}</div>
        </div>
        <div class="coda">
          <div class="posti-num${posti ? "" : " ignota"}">${posti
            ? p.capienza + `<span> posti</span>` : "capienza ignota"}</div>
        </div>
      </div>`;
    }
    h += `</div><div class="hint" style="padding:0 var(--lato)">${esc(d.avvertenza || "")}</div>`;
  }

  const ripari = d.ripari || [];
  if (ripari.length) {
    h += `<h2>Ripari nei paraggi</h2><div class="gruppo">`;
    for (const r of ripari.slice(0, 4)) {
      h += `<div class="voce" style="cursor:default">
        <div class="corpo">
          <div class="titolo" style="font-size:15.5px">${esc(r.etichetta)}</div>
          <div class="meta">${esc(r.genere || "")} &middot; ${r.distanza_km} km
            ${r.quota ? " &middot; " + r.quota + " m" : ""}</div>
        </div>
      </div>`;
    }
    h += `</div><div class="hint" style="padding:0 var(--lato)">Restano
      disponibili in <b>Emergenza</b> anche senza campo: li ho scaricati
      adesso, insieme alla scheda.</div>`;
  }
  box.innerHTML = h;
}

/* La rosa delle esposizioni, come la disegnano i bollettini.

   Non e' decorazione: "esposizioni N-NE-E, sopra 2200 m" scritto a parole
   richiede di fermarsi a leggere, la rosa si guarda e si e' capito. Il dato
   e' identico - quello che il bollettino dichiara - solo reso nella forma in
   cui chi va in montagna e' abituato a vederlo.

   SVG scritto a mano: nessuna libreria per otto triangoli. */
const ESPOSIZIONI = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"];

function rosaEsposizioni(esposizioni, lato = 66) {
  const attive = new Set(esposizioni || []);
  const c = lato / 2, r = c - 9;
  const punto = (gradi, raggio) => {
    const a = (gradi - 90) * Math.PI / 180;   // 0 gradi = nord = in alto
    return [c + raggio * Math.cos(a), c + raggio * Math.sin(a)];
  };
  let settori = "";
  ESPOSIZIONI.forEach((nome, i) => {
    const [x1, y1] = punto(i * 45 - 22.5, r);
    const [x2, y2] = punto(i * 45 + 22.5, r);
    settori += `<path d="M${c} ${c} L${x1.toFixed(1)} ${y1.toFixed(1)} `
      + `A${r} ${r} 0 0 1 ${x2.toFixed(1)} ${y2.toFixed(1)} Z" `
      + `class="rosa-set${attive.has(nome) ? " on" : ""}"/>`;
  });
  // le quattro lettere cardinali, appena fuori dal cerchio
  let lettere = "";
  [["N", 0], ["E", 90], ["S", 180], ["O", 270]].forEach(([t, g]) => {
    const [x, y] = punto(g, r + 6.5);
    lettere += `<text x="${x.toFixed(1)}" y="${(y + 2.6).toFixed(1)}" `
      + `class="rosa-txt">${t}</text>`;
  });
  return `<svg class="rosa" viewBox="0 0 ${lato} ${lato}" width="${lato}" height="${lato}"
    role="img" aria-label="esposizioni: ${esc((esposizioni || []).join(", ") || "nessuna")}">
    ${settori}<circle cx="${c}" cy="${c}" r="${r * 0.38}" class="rosa-buco"/>${lettere}</svg>`;
}

function fasciaQuota(pr) {
  if (pr.quota_min && pr.quota_max) return `fra ${pr.quota_min} e ${pr.quota_max} m`;
  if (pr.quota_min) return `sopra ${pr.quota_min} m`;
  if (pr.quota_max) return `sotto ${pr.quota_max} m`;
  return "a tutte le quote";
}

/* ------------------------------------------------------------ router */

const VISTE = {};
let vistaCorrente = "weekend";

/* Sapere non ha piu' una voce nella barra: ci si arriva dal profilo. Mentre
   lo si legge la barra resta accesa sul profilo, altrimenti si spegnerebbe
   tutta e non si capirebbe piu' dove si e'. */
const TAB_DI = { sapere: "profilo", emergenza: "profilo" };

function vai(nome, arg) {
  vistaCorrente = nome;
  const tab = TAB_DI[nome] || nome;
  document.querySelectorAll("nav button").forEach(b =>
    b.classList.toggle("on", b.dataset.vista === tab));
  // il GPS resta accesso finche' non glielo si dice: lasciarlo in ascolto
  // dopo aver chiuso Emergenza vorrebbe dire consumare batteria per
  // niente, ed e' batteria che in montagna serve
  if (SORVEGLIANZA !== null && nome !== "emergenza") {
    try { navigator.geolocation.clearWatch(SORVEGLIANZA); } catch (e) {}
    SORVEGLIANZA = null;
    POSIZIONE = null;
  }
  el.innerHTML = '<div class="carico">Carico...</div>';
  mappa = null;
  (VISTE[nome] || VISTE.weekend)(arg).catch(e => {
    el.innerHTML = `<div class="wrap"><div class="vuoto">Errore: ${esc(e.message)}</div></div>`;
  });
}
document.querySelectorAll("nav button").forEach(b =>
  b.addEventListener("click", () => { haptic(); vai(b.dataset.vista); }));

/* La fascia dei dati di prova. Sta in cima a OGNI schermata e non si puo'
   chiudere: un grado di pericolo mostrato senza contesto e' identico a
   quello di oggi, e qualcuno potrebbe usarlo per decidere una gita. Finche'
   la simulazione e' accesa, questo avviso e' l'unica cosa che lo impedisce. */
function mostraFasciaSimulazione(sim) {
  const box = document.getElementById("fascia-simulazione");
  if (!box) return;
  if (!sim || !sim.attiva) { box.hidden = true; box.textContent = ""; return; }
  box.textContent = sim.testo;
  box.hidden = false;
  // il contenuto scorre sotto la fascia: gli si fa spazio
  document.body.style.paddingTop = box.offsetHeight + "px";
}

/* ------------------------------------------------------------ weekend */

/* La striscia dei giorni: scorre di lato col dito.
   Sette giorni perche' e' quanto lontano guarda il modello meteo, e quanto
   ne scrive aggiorna.py: oltre non ci sarebbe niente da mostrare. */
function strisciaGiorni(scelto) {
  const oggi = new Date(); oggi.setHours(12, 0, 0, 0);
  let h = `<div class="striscia" id="striscia-giorni">`;
  for (let i = 0; i < 7; i++) {
    const d = new Date(oggi); d.setDate(d.getDate() + i);
    const iso = d.toISOString().slice(0, 10);
    const gs = d.getDay();                      // 0 domenica, 6 sabato
    h += `<button class="${iso === scelto ? "on" : ""}${gs === 0 || gs === 6 ? " fine" : ""}"
      onclick="vai('weekend','${iso}')">
      <span class="gs">${["dom", "lun", "mar", "mer", "gio", "ven", "sab"][gs]}</span>
      <span class="gn">${d.getDate()}</span>
    </button>`;
  }
  return h + `</div>`;
}

VISTE.weekend = async function (giorno) {
  const g = giorno || prossimoSabato();

  const dati = await api("/weekend?giorno=" + g);
  // titolo corto e sottotitolo di una riga: la spiegazione lunga sta in
  // fondo, nel disclaimer, dove non si mette fra il titolo e i dati
  let h = `<div class="wrap"><h1>Weekend</h1>
    <div class="hint">Dove e' caduta neve, e il grado ufficiale.</div>
    ${strisciaGiorni(g)}`;

  if (!dati.risultati.length) {
    h += `<div class="vuoto">Nessun dato meteo ancora scaricato.<br><br>
      Lancia <code>python scripts/aggiorna.py</code> per popolare la cache,
      o importa il catalogo se e' vuoto.</div>`;
  }

  /* Un elenco raggruppato: una superficie sola, righe separate da filetti.
     Prima erano schede staccate, e con dodici gite la pagina diventava una
     colonna di scatole in cui l'occhio non trovava piu' la riga. */
  if (dati.risultati.length) h += `<div class="gruppo">`;
  for (const r of dati.risultati) {
    const gr = r.valanghe_grado;
    const cm = r.neve.ha_nevicato ? Math.round(r.neve.neve_72h_cm) : null;
    h += `<div class="voce" onclick="vai('gita',{id:${r.gita.id},giorno:'${dati.giorno}'})">
      <div class="corpo">
        <div class="titolo">${esc(r.gita.nome)}</div>
        <div class="meta">${esc(r.gita.valle || r.gita.comune || "")}
          ${r.gita.dislivello ? " &middot; " + r.gita.dislivello + " m D+" : ""}
          ${r.gita.difficolta ? " &middot; " + esc(r.gita.difficolta) : ""}</div>
        ${r.neve.descrizione ? `<div class="meta" style="color:var(--terziario)">
          ${esc(r.neve.descrizione)}</div>` : ""}
      </div>
      <div class="coda">
        <div class="neve-cm">${cm !== null
          ? cm + `<span> cm</span>`
          : `<span class="niente">&mdash;</span>`}</div>
        ${gr ? `<div class="grado" style="font-size:13px">
          <span class="pallino g${gr}" style="width:15px;height:15px;border-radius:4px"></span>${gr}</div>` : ""}
      </div>
      ${FRECCIA}
    </div>`;
  }
  if (dati.risultati.length) h += `</div>`;
  if (dati.risultati.some(r => r.neve.ha_nevicato)) {
    h += `<div class="avviso grave">${esc(dati.avvertenza_neve || "")}</div>`;
  }
  h += `<div class="disclaimer">${esc(dati.disclaimer || "")}</div></div>`;
  el.innerHTML = h;

  // il giorno scelto puo' essere fuori dallo schermo: lo si porta al centro
  // senza animazione, altrimenti a ogni cambio la pagina "salta"
  const attivo = document.querySelector(".striscia button.on");
  if (attivo) attivo.scrollIntoView({ block: "nearest", inline: "center" });
};

/* ------------------------------------------------------------ elenco gite */

VISTE.gite = async function () {
  const dati = await api("/gite?limite=200");
  const valli = await api("/valli");
  let h = `<div class="wrap"><h1>Catalogo</h1>
    <div class="hint">${dati.totale} itinerari, da fonti aperte.</div>
    <input id="cerca" placeholder="Cerca una gita o un comune..." autocomplete="off"
      style="margin-top:12px">
    <div class="tag-riga" style="margin-top:10px">
      <span class="tag" data-valle="">tutte (${dati.totale})</span>
      ${valli.map(v => `<span class="tag" data-valle="${esc(v.valle)}">${esc(v.valle)} (${v.gite})</span>`).join("")}
    </div>
    <div id="lista" class="sez"></div>
    <div style="padding:0 var(--lato);margin-top:16px">
      <button class="secondario" style="width:100%" onclick="vai('nuovaGita')">
        + Aggiungi una gita che manca</button>
    </div>
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
  lista.innerHTML = `<div class="gruppo">` + gite.map(g => `
    <div class="voce" onclick="vai('gita',${g.id})">
      <div class="corpo">
        <div class="titolo">${esc(g.nome)}</div>
        <div class="meta">${esc(g.comune || "")}${g.valle ? " &middot; " + esc(g.valle) : ""}
          ${g.dislivello ? " &middot; " + g.dislivello + " m D+" : ""}
          ${g.difficolta ? " &middot; " + esc(g.difficolta) : ""}</div>
      </div>
      ${FRECCIA}
    </div>`).join("") + `</div>`;
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
    <div class="tag-riga">
      ${g.quota_min ? `<span class="tag">attacco ${g.quota_min} m</span>` : ""}
      ${g.quota_max ? `<span class="tag">cima ${g.quota_max} m</span>` : ""}
      ${g.dislivello ? `<span class="tag">${g.dislivello} m D+</span>` : ""}
      ${g.esposizione ? `<span class="tag">esp. ${esc(g.esposizione)}</span>` : ""}
      ${g.difficolta ? `<span class="tag">${esc(g.difficolta)}</span>` : ""}
    </div>`;

  /* --- avvicinamento: quanto ci metti, e da dove passi --- */
  h += `<div id="avvicinamento"></div>`;

  /* --- la traccia, col profilo e il GPX --- */
  h += `<div id="traccia"></div>`;

  /* --- all'attacco: parcheggi (con la capienza) e ripari --- */
  h += `<div id="posti"></div>`;

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
      Apri il bollettino ufficiale &rarr;</a>
      <div><a href="#" onclick="vai('sapere');return false"
        style="display:inline-block;margin-top:6px">Come si legge un
        bollettino &rarr;</a></div></div>`;
  } else {
    const gr = v.grado_massimo;
    h += `<div class="card">
      <div class="grado"><span class="pallino g${gr || 0}"></span>
        Grado ${gr || "-"} ${esc((v.gradi?.[0]?.testo) || "")}</div>
      ${v.problemi?.length ? `<div style="margin-top:12px">
        <div class="hint" style="margin-bottom:6px">Problemi segnalati dal bollettino,
          con le esposizioni e le quote che indica:</div>
        ${v.problemi.map(pr => `<div class="problema">
          ${rosaEsposizioni(pr.esposizioni)}
          <div style="min-width:0">
            <div class="titolo" style="font-size:14.5px">${esc(pr.tipo_it)}</div>
            <div class="meta">${esc(fasciaQuota(pr))}</div>
            <div class="meta">${pr.esposizioni.length
              ? "esposizioni " + pr.esposizioni.join(", ")
              : "esposizioni non specificate"}</div>
          </div></div>`).join("")}
      </div>` : ""}
      ${v.sintesi ? `<div class="meta" style="margin-top:9px">${esc(v.sintesi)}</div>` : ""}
      <div class="hint" style="margin-top:9px;font-size:11.5px">
        ${v.ente ? esc(v.ente) + " &middot; " : ""}${v.emesso_il ? "emesso " + esc(String(v.emesso_il).slice(0, 16).replace("T", " ")) : ""}</div>
      <a href="${v.link_ufficiale}" target="_blank"
        style="display:inline-block;margin-top:8px">Bollettino integrale &rarr;</a>
    </div>`;
    h += `<div class="avviso">Questo e' un estratto. <b>Il bollettino va letto
      per intero prima di uscire</b>: l'app non dice quali problemi riguardino
      questa gita, e non e' in grado di dirlo.
      <a href="#" onclick="vai('sapere');return false"
        style="display:inline-block;margin-top:6px">Come si legge un
        bollettino &rarr;</a></div>`;
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

  /* --- com'era: le condizioni viste da chi c'e' stato --- */
  h += `<div id="segnalazioni"></div>`;

  /* --- dopo la gita: le piole lungo la strada di casa --- */
  h += `<div id="piole"></div>`;

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

  if (!fuoriDaTelegram()) {
    const oggi = new Date().toISOString().slice(0, 10);
    h += `<h2>Ci sono stato</h2>
      <div class="card">
        <div class="hint">Il diario e' solo tuo: nessun altro lo vede, e non
          compare da nessuna parte accanto al tuo nome.</div>
        <label>Quando</label>
        <input type="date" id="data-fatta" max="${oggi}" value="${oggi}">
        <label>Nota per te (facoltativa)</label>
        <input id="nota-fatta" maxlength="500"
          placeholder="com'e' andata, con chi, cosa rifarei...">
        <div class="hint">Com'era la neve raccontalo sopra, in
          &laquo;Com'era&raquo;: quello lo leggono gli altri. Questo no.</div>
        <button class="secondario" style="margin-top:10px" id="segna-fatta">
          Segna nel diario</button>
        <div id="esito-fatta"></div>
      </div>`;
  }

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

  document.getElementById("segna-fatta")?.addEventListener("click", async () => {
    try {
      const r = await api("/fatte", {
        method: "POST",
        body: JSON.stringify({
          gita_id: g.id,
          data: document.getElementById("data-fatta").value,
          nota: document.getElementById("nota-fatta").value || null,
        }),
      });
      haptic();
      avviso("esito-fatta", r.aggiornata
        ? "Nota aggiornata nel diario." : "Segnata nel diario.", "ok");
    } catch (e) {
      avviso("esito-fatta", e.message);
    }
  });

  // non si attendono: la scheda e' gia' a schermo e questi arrivano dopo
  disegnaAvvicinamento(g.id);
  disegnaSegnalazioni(g.id);
  disegnaPosti(g, m.tramonto);
  disegnaTraccia(g);
};

/* --------------------------------------------- condizioni viste (segnalazioni)

   Il vocabolario delle etichette arriva dal server (app/segnalazioni.py):
   qui non si scrive nessuna etichetta a mano, altrimenti fra sei mesi ce ne
   sarebbero due elenchi diversi e uno dei due sbagliato.

   E' chiuso di proposito: un campo libero, in questo posto, diventa in
   fretta "tranquilla, si va" - la frase che fa partire qualcuno senza
   leggere il bollettino. Vedi il commento in cima a app/segnalazioni.py. */

const SEGN = { neve: new Set(), accesso: new Set(), traccia: null };

function pillole(gruppo, voci) {
  return Object.entries(voci || {}).map(([k, t]) =>
    `<button type="button" class="pillola" data-gruppo="${gruppo}"
      data-chiave="${esc(k)}">${esc(t)}</button>`).join("");
}

function cartaSegnalazione(s) {
  return `<div class="card${s.fresca ? "" : " vecchia"}">
    <div class="riga">
      <div style="min-width:0">
        <div class="titolo" style="font-size:14.5px">${esc(s.quando)}
          <span class="hint" style="font-weight:400">&middot; ${dataIt(s.giorno)}</span></div>
        <div style="margin-top:6px">${s.etichette.map(e =>
          `<span class="tag">${esc(e)}</span>`).join("")}</div>
        ${s.nota ? `<div class="meta" style="margin-top:6px">&laquo;${esc(s.nota)}&raquo;</div>` : ""}
        <div class="meta" style="margin-top:6px">${esc(s.autore?.nome || "qualcuno")}</div>
        ${rigaEsperienza(s.autore)}
      </div>
      ${s.mia ? `<button class="secondario" style="padding:5px 9px;font-size:12px"
        onclick="togliSegnalazione(${s.id})">togli</button>` : ""}
    </div>
    ${s.fresca ? "" : `<div class="hint" style="margin-top:8px">Sono passati
      ${s.giorni_fa} giorni: con una notte di vento o un rialzo termico la
      neve che trovi non e' questa.</div>`}
  </div>`;
}

async function disegnaSegnalazioni(gitaId) {
  const box = document.getElementById("segnalazioni");
  if (!box) return;
  let d;
  try {
    d = await api("/segnalazioni/" + gitaId);
  } catch (e) {
    box.innerHTML = "";     // e' un di piu': la scheda resta completa
    return;
  }
  if (!box.isConnected) return;    // schermata gia' cambiata

  const voc = d.vocabolario || {};
  SEGN.neve = new Set(); SEGN.accesso = new Set(); SEGN.traccia = null;

  const oggi = new Date().toISOString().slice(0, 10);
  // oltre questa data il server rifiuta: la neve di allora non c'e' piu'
  const primo = new Date();
  primo.setDate(primo.getDate() - (voc.giorni_validi || 30));
  const daQuando = primo.toISOString().slice(0, 10);

  let h = `<h2>Com'era</h2>`;
  if (!d.segnalazioni.length) {
    h += `<div class="card"><div class="hint">Nessuno ha ancora raccontato
      com'era, in queste settimane. Il bollettino dice com'e' il manto su
      mezza valle: se la strada era aperta fino all'attacco lo sa solo chi
      c'e' passato.</div></div>`;
  } else {
    h += d.segnalazioni.map(cartaSegnalazione).join("");
  }

  if (!fuoriDaTelegram()) {
    h += `<div class="card" style="margin-top:14px">
      <div class="titolo" style="font-size:15px">Racconta com'era</div>
      <label>Quando ci sei stato</label>
      <input type="date" id="sg-giorno" value="${oggi}" min="${daQuando}" max="${oggi}">

      <label>Com'era la neve</label>
      <div class="pillole" id="sg-neve">${pillole("neve", voc.neve)}</div>
      <div class="hint" id="sg-neve-nota">Al massimo ${voc.max_neve || 3}:
        se scegli tutto non hai detto niente.</div>

      <label>A che quota cambiava, se cambiava</label>
      <input type="number" id="sg-quota" inputmode="numeric" placeholder="facoltativo, es. 2100"
        min="${voc.quota_min || 500}" max="${voc.quota_max || 3400}">

      <label>La traccia</label>
      <div class="pillole" id="sg-traccia">${pillole("traccia", voc.traccia)}</div>

      <label>La strada e il parcheggio</label>
      <div class="pillole" id="sg-accesso">${pillole("accesso", voc.accesso)}</div>

      <label>Una nota, se serve</label>
      <input id="sg-nota" maxlength="${voc.max_nota || 140}"
        placeholder="un dettaglio che le etichette non dicono...">
      <div class="hint" id="sg-conta">${voc.max_nota || 140} caratteri.
        Serve a raccontare cosa hai visto, non a dare consigli.</div>

      <div class="avviso" style="margin-top:12px">${esc(voc.avvertenza || "")}</div>
      <button class="primario" id="sg-invia">Racconta com'era</button>
      <div id="sg-esito"></div>
      <div class="hint">La vedranno gli altri sulla scheda della gita, col tuo
        nome e la data. Se hai gia' raccontato questo giorno, la tua
        segnalazione viene aggiornata.</div>
    </div>`;
  }
  box.innerHTML = h;
  if (fuoriDaTelegram()) return;

  /* le pillole: nessun onclick nell'HTML, cosi' le etichette che arrivano
     dal server non finiscono mai dentro una stringa JavaScript */
  box.querySelectorAll(".pillola").forEach(b => b.addEventListener("click", () => {
    const g = b.dataset.gruppo, k = b.dataset.chiave;
    haptic();
    if (g === "traccia") {                        // una sola risposta
      SEGN.traccia = SEGN.traccia === k ? null : k;
      box.querySelectorAll('[data-gruppo="traccia"]').forEach(x =>
        x.classList.toggle("on", x.dataset.chiave === SEGN.traccia));
      return;
    }
    const insieme = SEGN[g];
    if (insieme.has(k)) {
      insieme.delete(k);
    } else {
      const max = g === "neve" ? (voc.max_neve || 3) : 99;
      if (insieme.size >= max) {
        avviso("sg-esito", `Al massimo ${max} etichette per la neve: `
          + "togline una, se vuoi cambiarla.");
        return;
      }
      insieme.add(k);
    }
    b.classList.toggle("on", insieme.has(k));
    avviso("sg-esito", "");
  }));

  const nota = document.getElementById("sg-nota");
  const conta = document.getElementById("sg-conta");
  nota.addEventListener("input", () => {
    const restano = (voc.max_nota || 140) - nota.value.length;
    conta.textContent = `${restano} caratteri. Serve a raccontare cosa hai `
      + "visto, non a dare consigli.";
  });

  const bottone = document.getElementById("sg-invia");
  bottone.addEventListener("click", async () => {
    const corpo = {
      gita_id: gitaId,
      giorno: document.getElementById("sg-giorno").value,
      neve: [...SEGN.neve],
      traccia: SEGN.traccia,
      accesso: [...SEGN.accesso],
      quota_cambio: valoreNumero("sg-quota"),
      nota: valore("sg-nota"),
    };
    bottone.disabled = true;
    try {
      const r = await api("/segnalazioni", { method: "POST", body: JSON.stringify(corpo) });
      haptic();
      // prima si ridisegna (la nuova segnalazione compare in cima), POI si
      // scrive l'esito: nell'ordine inverso il ridisegno cancellerebbe il
      // messaggio e l'utente non saprebbe se e' andata
      await disegnaSegnalazioni(gitaId);
      avviso("sg-esito", r.aggiornata ? "Aggiornata, grazie." : "Grazie: e' online.", "ok");
    } catch (e) {
      avviso("sg-esito", e.message);
      bottone.disabled = false;
    }
  });
}

window.togliSegnalazione = async function (id) {
  const box = document.getElementById("segnalazioni");
  try {
    await api("/segnalazioni/" + id, { method: "DELETE" });
    haptic();
    if (GITA_CORRENTE) disegnaSegnalazioni(GITA_CORRENTE.id);
  } catch (e) {
    if (box) avviso("sg-esito", e.message);
  }
};

/* Il diario privato. La riga che conta e' il commento sul modello Fatta:
   un contatore di gite visibile diventa in fretta una classifica, e una
   classifica in montagna spinge nella direzione sbagliata. Per questo il
   diario sta qui, nel profilo di chi lo scrive, e da nessun'altra parte. */
async function disegnaDiario() {
  const box = document.getElementById("diario");
  if (!box || fuoriDaTelegram()) return;
  let righe;
  try {
    righe = await api("/fatte");
  } catch (e) {
    box.innerHTML = `<div class="hint">Diario non disponibile: ${esc(e.message)}</div>`;
    return;
  }
  if (!righe.length) {
    box.innerHTML = `<div class="hint">Ancora niente. Apri una gita e usa
      &laquo;Ci sono stato&raquo;.</div>`;
    return;
  }
  // per stagione, non per anno civile: un inverno sta a cavallo di due anni,
  // e "2026" spezzerebbe a metà la stagione di chi scia a gennaio
  const perStagione = {};
  for (const f of righe) {
    const d = new Date(f.data + "T00:00:00");
    const a = d.getMonth() >= 8 ? d.getFullYear() : d.getFullYear() - 1;
    const nome = `${a}/${String(a + 1).slice(2)}`;
    (perStagione[nome] = perStagione[nome] || []).push(f);
  }
  box.innerHTML = Object.keys(perStagione).sort().reverse().map(st => `
    <div class="hint" style="margin:12px 0 6px">Stagione ${esc(st)} &mdash;
      ${perStagione[st].length} ${perStagione[st].length === 1 ? "uscita" : "uscite"}</div>
    ${perStagione[st].map(f => `<div class="card" style="padding:10px 12px">
      <div class="riga">
        <div style="min-width:0">
          <div class="titolo" style="font-size:14.5px">${esc(f.gita?.nome || "gita rimossa")}</div>
          <div class="meta">${dataIt(f.data)}</div>
          ${f.nota ? `<div class="meta">${esc(f.nota)}</div>` : ""}
        </div>
        <button class="secondario" style="padding:5px 9px;font-size:12px"
          onclick="scordaFatta(${f.id})">togli</button>
      </div></div>`).join("")}`).join("");
}

window.scordaFatta = async function (id) {
  try {
    await api("/fatte/" + id, { method: "DELETE" });
    haptic();
    disegnaDiario();
  } catch (e) { /* si rilegge riaprendo il profilo */ }
};

/* ----------------------------------------------------------- la traccia

   Una linea su una mappa, in montagna, e' un invito a seguirla: quindi
   accanto alla linea si scrive sempre CHI L'HA DISEGNATA. Le parole della
   provenienza arrivano dal server (app/tracce.py, ORIGINI), non le scrive
   il JavaScript - come per le condizioni, il vocabolario sta in un posto
   solo. */

/* Il profilo altimetrico: SVG scritto a mano, nessuna libreria per
   disegnare una linea. Serve a leggere la FORMA della salita - dove sono i
   pianori e dove il muro - non a misurare metri: le quote vengono da un
   modello del terreno a maglia di qualche decina di metri, e lo diciamo. */
function profiloSvg(punti, largo = 358, alto = 96) {
  if (!punti || punti.length < 2) return "";
  const quote = punti.map(p => p[1]);
  const kmMax = punti[punti.length - 1][0] || 1;
  let qMin = Math.min(...quote), qMax = Math.max(...quote);
  if (qMax - qMin < 50) { qMax = qMin + 50; }         // una salita piatta non si schiaccia
  const margine = 16;
  const x = km => margine + (largo - margine * 2) * (km / kmMax);
  const y = q => alto - 18 - (alto - 34) * ((q - qMin) / (qMax - qMin));

  const linea = punti.map((p, i) =>
    `${i ? "L" : "M"}${x(p[0]).toFixed(1)} ${y(p[1]).toFixed(1)}`).join("");
  const area = `${linea}L${x(kmMax).toFixed(1)} ${alto - 18}L${x(0).toFixed(1)} ${alto - 18}Z`;

  return `<svg class="profilo" viewBox="0 0 ${largo} ${alto}" width="100%"
      height="${alto}" role="img"
      aria-label="profilo altimetrico: da ${Math.round(qMin)} a ${Math.round(qMax)} metri in ${kmMax.toFixed(1)} chilometri">
    <path class="pr-area" d="${area}"/>
    <path class="pr-linea" d="${linea}"/>
    <text class="pr-txt" x="2" y="12">${Math.round(qMax)} m</text>
    <text class="pr-txt" x="2" y="${alto - 4}">${Math.round(qMin)} m</text>
    <text class="pr-txt" x="${largo - 2}" y="${alto - 4}"
      text-anchor="end">${kmMax.toFixed(1)} km</text>
  </svg>`;
}

async function disegnaTraccia(gita) {
  const box = document.getElementById("traccia");
  if (!box) return;
  let d;
  try {
    d = await api("/traccia/" + gita.id);
  } catch (e) {
    box.innerHTML = "";
    return;
  }
  if (!box.isConnected) return;

  if (d.stato === "assente") {
    // non e' un errore ed e' importante dirlo: per una parte del catalogo
    // la fonte pubblica solo il punto dell'attacco
    box.innerHTML = `<h2>Traccia</h2>
      <div class="card"><div class="hint">${esc(d.spiega || "")}</div>
      ${fuoriDaTelegram() ? "" : `<div class="hint" style="margin-top:8px">Se
        l'hai fatta e hai la registrazione, puoi caricarla qui sotto.</div>`}
      ${modulodiCaricamento(gita)}</div>`;
    collegaCaricamento(gita);
    return;
  }

  const dislPari = d.dislivello_plausibile === false;
  box.innerHTML = `<h2>Traccia</h2>
    <div class="card">
      <div class="riga">
        <div style="min-width:0">
          <div class="titolo" style="font-size:15px">${esc(d.origine_etichetta)}</div>
          <div class="meta">${esc(d.origine_spiega)}</div>
        </div>
      </div>
      ${d.con_quote ? profiloSvg(d.profilo) : `<div class="hint"
        style="margin-top:10px">Profilo altimetrico non disponibile: la
        traccia non ha le quote.</div>`}
      <div class="dato" style="margin-top:6px">
        ${d.lunghezza_km ? `<div><div class="k">Sviluppo</div>
          <div class="v">${d.lunghezza_km} km</div></div>` : ""}
        ${d.dislivello_dichiarato ? `<div><div class="k">Dislivello</div>
          <div class="v">${d.dislivello_dichiarato} m</div></div>` : ""}
        <div><div class="k">Punti</div><div class="v">${d.punti_totali}</div></div>
      </div>
      ${d.con_quote ? `<div class="hint" style="margin-top:10px">Le quote
        vengono da un modello del terreno: servono a vedere la forma della
        salita, non a misurare un salto di roccia. Il dislivello mostrato e'
        quello <b>dichiarato dalla fonte</b>${d.dislivello_dalla_traccia
          ? ` (dalla traccia risulterebbe ${d.dislivello_dalla_traccia} m)` : ""}.</div>` : ""}
      ${dislPari ? `<div class="avviso">Il dislivello dichiarato
        (${d.dislivello_dichiarato} m) e quello che risulta dalla traccia
        (${d.dislivello_dalla_traccia} m) sono molto diversi: uno dei due e'
        sbagliato, e non sappiamo quale. Controlla sulla fonte.</div>` : ""}
      ${d.adatta_a_sci ? "" : `<div class="avviso grave">Questo percorso e'
        <b>calcolato</b>, non registrato: non e' la traccia di una gita di
        scialpinismo, e d'inverno la linea giusta non e' il sentiero
        estivo.</div>`}
      <button class="secondario" style="width:100%;margin-top:12px"
        onclick="scaricaGpx(${gita.id})">Scarica il GPX</button>
      ${d.licenza ? `<div class="disclaimer">${esc(d.licenza)}${d.autori
        ? " &mdash; " + esc(d.autori) : ""}. L'attribuzione viaggia dentro il
        file GPX, non solo qui.</div>` : ""}
      ${modulodiCaricamento(gita)}
    </div>`;
  collegaCaricamento(gita);

  // la linea sulla mappa che la scheda ha gia' disegnato
  if (mappa && typeof L !== "undefined" && d.punti?.length) {
    try {
      const linea = L.polyline(d.punti.map(p => [p[0], p[1]]),
        { color: "#C0281C", weight: 3.5, opacity: .85 }).addTo(mappa);
      mappa.fitBounds(linea.getBounds(), { padding: [18, 18] });
    } catch (e) { /* la mappa e' un di piu': se non c'e', pazienza */ }
  }
}

function modulodiCaricamento(gita) {
  if (fuoriDaTelegram()) return "";
  return `<div style="margin-top:14px;border-top:1px solid var(--filetto);padding-top:12px">
    <div class="hint"><b>Carica la tua traccia.</b> Solo una registrazione
      fatta da te: quella e' tua e puoi darla all'app. Le tracce scaricate
      da altri siti no &mdash; non sono nostre da ridistribuire, ed e' la
      stessa ragione per cui non copiamo i cataloghi degli altri.</div>
    <label class="secondario" for="gpx-file"
      style="display:block;text-align:center;margin:10px 0 0;cursor:pointer;
             line-height:22px;font-size:14.5px">Scegli un file GPX</label>
    <input type="file" id="gpx-file" accept=".gpx,application/gpx+xml" hidden>
    <div id="esito-gpx"></div>
  </div>`;
}

function collegaCaricamento(gita) {
  const campo = document.getElementById("gpx-file");
  if (!campo) return;
  campo.addEventListener("change", async () => {
    const file = campo.files?.[0];
    if (!file) return;
    if (file.size > 6_000_000) {
      avviso("esito-gpx", "File troppo grande (oltre 6 MB).");
      return;
    }
    avviso("esito-gpx", "");
    let testo;
    try {
      testo = await file.text();
    } catch (e) {
      avviso("esito-gpx", "Non riesco a leggere il file.");
      return;
    }
    try {
      await api("/traccia/" + gita.id, {
        method: "POST", body: JSON.stringify({ gpx: testo }), timeout: 30000,
      });
      haptic();
      await disegnaTraccia(gita);
      avviso("esito-gpx", "Caricata. Grazie: e' la traccia migliore che "
        + "questa gita puo' avere.", "ok");
    } catch (e) {
      avviso("esito-gpx", e.message);
    }
  });
}

/* Il GPX si apre fuori dal webview: dentro Telegram un download parte a
   volte e a volte no, e un pulsante che non fa niente e' peggio di un
   pulsante che manda al browser. */
window.scaricaGpx = function (gitaId) {
  const url = location.origin + "/api/gpx/" + gitaId;
  haptic();
  if (TG?.openLink) TG.openLink(url);
  else window.open(url, "_blank");
};

/* --------------------------------------------------------- emergenza

   La schermata piu' importante dell'app e' quella che si spera di non
   aprire mai. Due principi, e sono l'opposto di come e' fatto tutto il
   resto:

   1. DEVE FUNZIONARE SENZA RETE. In valle il campo non c'e', ed e'
      esattamente il momento in cui serve. Quindi: niente chiamate al
      server. I ripari e l'ora del tramonto si scaricano PRIMA, quando si
      apre la scheda di una gita e la rete c'e' ancora, e si tengono nel
      telefono. La posizione la da' il GPS, che funziona anche senza campo.
   2. LA POSIZIONE NON ESCE DA QUI. Non la mandiamo al nostro server: il
      riparo piu' vicino lo calcola il telefono sui dati che ha gia'. Il
      solo momento in cui la posizione se ne va e' quando la persona tocca
      "prepara il messaggio" - e a quel punto e' Telegram a chiedere a chi,
      e a farla premere invio. */

const CHIAVE_EMERGENZA = "ndoma.emergenza";

function leggiEmergenza() {
  try {
    return JSON.parse(localStorage.getItem(CHIAVE_EMERGENZA) || "null");
  } catch (e) {
    return null;   /* finestra privata, dati bloccati: si va avanti senza */
  }
}

/* Si tiene da parte quello che in emergenza non si potrebbe scaricare.
   I ripari si accumulano fra una scheda e l'altra: chi ha guardato tre
   gite della valle ha in tasca i ripari di tutte tre. */
function ricordaPerEmergenza(gita, ripari, tramonto) {
  try {
    const vecchio = leggiEmergenza() || {};
    const per_url = new Map();
    for (const r of (vecchio.ripari || []).concat(ripari || [])) {
      if (r && r.osm_url) per_url.set(r.osm_url, r);
    }
    localStorage.setItem(CHIAVE_EMERGENZA, JSON.stringify({
      quando: Date.now(),
      gita: { nome: gita.nome, lat: gita.lat, lon: gita.lon },
      tramonto: tramonto || vecchio.tramonto || null,
      ripari: [...per_url.values()].slice(-40),
    }));
  } catch (e) { /* niente da fare: la schermata funziona anche senza */ }
}

function distanzaKm(lat1, lon1, lat2, lon2) {
  const R = 6371, r = Math.PI / 180;
  const dLat = (lat2 - lat1) * r, dLon = (lon2 - lon1) * r;
  const a = Math.sin(dLat / 2) ** 2
    + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

const PUNTI = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"];

function direzione(lat1, lon1, lat2, lon2) {
  const r = Math.PI / 180;
  const y = Math.sin((lon2 - lon1) * r) * Math.cos(lat2 * r);
  const x = Math.cos(lat1 * r) * Math.sin(lat2 * r)
    - Math.sin(lat1 * r) * Math.cos(lat2 * r) * Math.cos((lon2 - lon1) * r);
  const gradi = (Math.atan2(y, x) / r + 360) % 360;
  return PUNTI[Math.round(gradi / 45) % 8];
}

VISTE.emergenza = async function () {
  const salvato = leggiEmergenza();
  const ripari = salvato?.ripari || [];

  el.innerHTML = `<div class="wrap">
    <button class="torna" onclick="vai('profilo')">&larr; profilo</button>
    <h1>Emergenza</h1>
    <div class="hint">Funziona senza rete: la posizione la da' il GPS e i
      ripari sono gia' nel telefono. Solo la chiamata ha bisogno di campo.</div>

    <h2>Da dettare al centralinista</h2>
    <div class="card" id="box-posizione">
      <div class="gps cerca"><span class="led"></span>Cerco il GPS...</div>
      <div class="coord" style="margin-top:10px">--.-----<br>--.-----</div>
      <div class="hint" style="margin-top:8px">gradi decimali, WGS84</div>
    </div>
    <div class="scelte" style="margin-top:0">
      <button id="copia">Copia</button>
      <button id="condividi">Prepara il messaggio</button>
    </div>
    <div id="esito-copia"></div>

    <h2>Chiamare</h2>
    <a class="sos" href="tel:112" style="text-decoration:none">
      <svg viewBox="0 0 24 24"><path d="M6.5 3h3l1.5 4-2 1.5a12 12 0 0 0 6.5 6.5L17 13l4 1.5v3a2 2 0 0 1-2.2 2A17 17 0 0 1 4 5.2 2 2 0 0 1 6.5 3Z"/></svg>
      <div><div class="n">Chiama 112</div>
        <div class="d">Numero unico europeo per le emergenze</div></div>
    </a>
    <div class="card"><div class="hint">Il segnale nelle valli chiuse spesso
      non c'e': migliora sui crinali e verso i paesi. Se non hai campo prova a
      salire di quota prima di rinunciare. <b>Una chiamata al 112 parte anche
      con la rete di un altro operatore</b>, quindi vale la pena provare
      comunque.</div></div>

    <h2>Al riparo piu' vicino</h2>
    <div id="box-ripari"></div>

    <h2>Primo soccorso</h2>
    <div class="gruppo">
      <div class="voce" onclick="apriFuori('https://www.aineva.it/')">
        <div class="corpo"><div class="titolo" style="font-size:15.5px">Autosoccorso in valanga &mdash; AINEVA</div></div>
        ${FRECCIA}
      </div>
      <div class="voce" onclick="apriFuori('https://www.cai.it/')">
        <div class="corpo"><div class="titolo" style="font-size:15.5px">Le guide del CAI</div></div>
        ${FRECCIA}
      </div>
    </div>
    <div class="disclaimer">Le manovre di primo soccorso non le scriviamo noi:
      si rimanda a chi le insegna e le tiene aggiornate. Quello che fa l'app,
      qui, e' darti la posizione esatta da dettare e il numero da chiamare.
      ${salvato ? `<br><br>Ripari salvati: ${ripari.length}, aggiornati il
        ${new Date(salvato.quando).toLocaleDateString("it-IT")}.`
      : `<br><br><b>Nessun riparo salvato.</b> Apri la scheda di una gita
        quando hai campo: i ripari intorno vengono scaricati e restano qui.`}
    </div>
  </div>`;

  disegnaRipari(ripari);
  seguiPosizione(ripari);

  document.getElementById("copia").addEventListener("click", async () => {
    if (!POSIZIONE) { avviso("esito-copia", "Non ho ancora la posizione."); return; }
    const t = testoPosizione();
    try {
      await navigator.clipboard.writeText(t);
      haptic();
      avviso("esito-copia", "Copiato.", "ok");
    } catch (e) {
      avviso("esito-copia", "Non riesco a copiare. Le coordinate sono qui sopra.");
    }
  });

  document.getElementById("condividi").addEventListener("click", () => {
    if (!POSIZIONE) { avviso("esito-copia", "Non ho ancora la posizione."); return; }
    // Telegram apre l'elenco delle chat: a chi mandarlo, e l'invio, li
    // decide la persona. Noi prepariamo solo il testo.
    const url = "https://t.me/share/url?url="
      + encodeURIComponent(`https://www.openstreetmap.org/?mlat=${POSIZIONE.lat}&mlon=${POSIZIONE.lon}#map=15/${POSIZIONE.lat}/${POSIZIONE.lon}`)
      + "&text=" + encodeURIComponent(testoPosizione());
    haptic();
    if (TG?.openTelegramLink) TG.openTelegramLink(url);
    else window.open(url, "_blank");
  });
};

window.apriFuori = function (url) {
  if (TG?.openLink) TG.openLink(url); else window.open(url, "_blank");
};

function testoPosizione() {
  const p = POSIZIONE;
  const righe = [
    `Sono a ${p.lat.toFixed(5)}, ${p.lon.toFixed(5)}`,
    `precisione ${Math.round(p.precisione)} m`,
  ];
  if (p.quota) righe.push(`quota ${Math.round(p.quota)} m`);
  righe.push(`(Ndoma a skie', ${new Date().toLocaleTimeString("it-IT").slice(0, 5)})`);
  return righe.join(" - ");
}

function seguiPosizione(ripari) {
  const box = document.getElementById("box-posizione");
  if (!box) return;
  if (!navigator.geolocation) {
    box.innerHTML = `<div class="gps no"><span class="led"></span>
      Questo telefono non da' la posizione</div>
      <div class="hint" style="margin-top:8px">Il 112 qui sopra funziona
      comunque: il centralinista puo' localizzarti lui.</div>`;
    return;
  }
  if (SORVEGLIANZA !== null) navigator.geolocation.clearWatch(SORVEGLIANZA);
  SORVEGLIANZA = navigator.geolocation.watchPosition(
    (pos) => {
      POSIZIONE = {
        lat: pos.coords.latitude, lon: pos.coords.longitude,
        precisione: pos.coords.accuracy, quota: pos.coords.altitude,
      };
      disegnaPosizione();
      disegnaRipari(ripari);
    },
    (err) => {
      if (!box.isConnected) return;
      box.innerHTML = `<div class="gps no"><span class="led"></span>
        Posizione non disponibile</div>
        <div class="hint" style="margin-top:8px">${err.code === 1
          ? "Il permesso e' stato negato: si concede dalle impostazioni del telefono."
          : "Sotto una parete o in un bosco fitto il GPS puo' metterci un minuto. Resta fermo all'aperto."}
        <br>Il 112 funziona comunque.</div>`;
    },
    { enableHighAccuracy: true, timeout: 20000, maximumAge: 5000 }
  );
}

async function disegnaPosizione() {
  const box = document.getElementById("box-posizione");
  if (!box || !box.isConnected || !POSIZIONE) return;
  const p = POSIZIONE;
  const buono = p.precisione <= 25;
  const salvato = leggiEmergenza();

  let batteria = null;
  try {
    if (navigator.getBattery) {
      const b = await navigator.getBattery();
      batteria = Math.round(b.level * 100);
    }
  } catch (e) { /* Safari non lo espone: si mostra il resto */ }

  box.innerHTML = `
    <div class="gps ${buono ? "" : "cerca"}"><span class="led"></span>
      ${buono ? "GPS fisso" : "GPS impreciso"} &middot;
      &plusmn;${Math.round(p.precisione)} m</div>
    <div class="coord" style="margin-top:10px">${p.lat.toFixed(5)}<br>${p.lon.toFixed(5)}</div>
    <div class="hint" style="margin-top:8px">gradi decimali, WGS84 &mdash;
      leggile cifra per cifra</div>
    <div class="dato">
      <div><div class="k">Quota</div>
        <div class="v">${p.quota ? Math.round(p.quota) + " m" : "&mdash;"}</div></div>
      ${batteria !== null ? `<div><div class="k">Batteria</div>
        <div class="v">${batteria}%</div></div>` : ""}
      ${salvato?.tramonto ? `<div><div class="k">Tramonto</div>
        <div class="v">${esc(salvato.tramonto)}</div></div>` : ""}
    </div>`;
}

function disegnaRipari(ripari) {
  const box = document.getElementById("box-ripari");
  if (!box || !box.isConnected) return;
  if (!ripari.length) {
    box.innerHTML = `<div class="card"><div class="hint">Nessun riparo
      salvato. Si scaricano da soli quando apri la scheda di una gita con
      il campo: da quel momento restano qui anche senza rete.</div></div>`;
    return;
  }
  let elenco = ripari.map(r => ({ ...r }));
  if (POSIZIONE) {
    for (const r of elenco) {
      r.km = distanzaKm(POSIZIONE.lat, POSIZIONE.lon, r.lat, r.lon);
      r.dir = direzione(POSIZIONE.lat, POSIZIONE.lon, r.lat, r.lon);
      r.dislivello = r.quota && POSIZIONE.quota
        ? Math.round(r.quota - POSIZIONE.quota) : null;
    }
    elenco.sort((a, b) => a.km - b.km);
  }
  box.innerHTML = `<div class="gruppo">
    ${elenco.slice(0, 4).map(r => `<div class="voce" style="cursor:default">
      <div class="corpo">
        <div class="titolo" style="font-size:15.5px">${esc(r.etichetta || r.nome || "Riparo")}</div>
        <div class="meta">${esc(r.genere || "")}
          ${r.km !== undefined ? ` &middot; ${r.km.toFixed(1)} km ${r.dir}` : ""}
          ${r.dislivello ? ` &middot; ${r.dislivello > 0 ? "+" : ""}${r.dislivello} m` : ""}</div>
      </div>
    </div>`).join("")}
  </div>
  <div class="hint" style="padding:0 var(--lato)">Da OpenStreetMap, scaricati
    con le schede delle gite. Le distanze sono in linea d'aria: <b>in montagna
    la strada e' sempre piu' lunga</b>, e di notte o con la nebbia molto di
    piu'.</div>`;
}

/* ------------------------------------------------------------- sapere */

/* Rimandi a chi sa, non copie di cio' che sa.
   Tutto quello che serve per decidere una gita sta su siti mantenuti da
   servizi valanghe e istituti di ricerca: linkarli e' l'unica cosa corretta
   da fare, sia per il diritto d'autore che perche' loro li aggiornano e noi
   no. Se ti viene voglia di trascrivere qui una tabella che hai visto in
   giro, rileggi questo commento. */
const SAPERE = [
  {
    titolo: "Il bollettino, prima di ogni uscita",
    nota: "L'app ne riporta un estratto. Quello che fa fede e' questo.",
    voci: [
      ["Bollettino valanghe Piemonte (ARPA)", "https://www.arpa.piemonte.it/bollettino/pericolo-valanghe",
       "Versante italiano. Emesso ogni giorno dopo le 17, da dicembre a maggio."],
      ["Risques d'avalanche - Alpes du Sud (Meteo-France)", "https://meteofrance.com/meteo-montagne/alpes-du-sud/risques-avalanche",
       "Versante francese: Mercantour, Ubaye, alta Tinee."],
      ["Tutti i bollettini italiani (AINEVA)", "https://bollettini.aineva.it/",
       "Se esci fuori dal Piemonte."],
    ],
  },
  {
    titolo: "Capire cosa c'e' scritto",
    nota: "Le definizioni ufficiali europee: sono le stesse parole che leggi nel bollettino.",
    voci: [
      ["La scala del pericolo, 1-5 (EAWS)", "https://www.avalanches.org/standards/avalanche-danger-scale/",
       "Cosa vuol dire davvero \"grado 3\", che non e' \"medio\"."],
      ["I problemi tipo (EAWS)", "https://www.avalanches.org/standards/avalanche-problems/",
       "Neve fresca, neve ventata, strato debole persistente, neve bagnata, slittamento: sono quelli che l'app ti mostra con la rosa delle esposizioni."],
    ],
  },
  {
    titolo: "Imparare per davvero",
    nota: "Niente di tutto questo si impara da un'app, nemmeno da questa.",
    voci: [
      ["White Risk (SLF Davos)", "https://www.whiterisk.ch",
       "La piattaforma dell'istituto svizzero per la neve e le valanghe: lezioni, pianificazione, e l'Analyser per valutare le situazioni tipiche sul posto. In parte gratuita."],
      ["AINEVA - formazione e manuali", "https://www.aineva.it/",
       "Corsi e pubblicazioni dell'associazione dei servizi valanghe italiani."],
      ["Le scuole di scialpinismo del CAI", "https://www.cai.it/",
       "Un corso vero, con gente che ti guarda mentre sbagli. Vale piu' di qualunque schermo."],
    ],
  },
];

VISTE.sapere = async function () {
  // non e' piu' una voce della barra: ci si arriva dal profilo o dai rimandi
  // dentro la scheda gita, quindi serve un modo di tornare indietro
  let h = `<div class="wrap">
    <button class="torna" onclick="vai('profilo')">&larr; profilo</button>
    <h1>Sapere</h1>
    <div class="hint">Quello che serve per decidere una gita non sta in
      quest'app: sta sui siti di chi emette i bollettini e di chi insegna.
      Qui ci sono i rimandi, aggiornati da loro.</div>`;

  for (const sez of SAPERE) {
    h += `<h2>${esc(sez.titolo)}</h2>
      <div class="hint" style="margin:-4px 0 8px">${esc(sez.nota)}</div>`;
    h += `<div class="gruppo">`;
    for (const [nome, url, spiega] of sez.voci) {
      h += `<a class="voce" href="${esc(url)}" target="_blank" rel="noopener"
        style="text-decoration:none;color:inherit">
        <div class="corpo">
          <div class="titolo" style="font-size:15.5px">${esc(nome)}</div>
          <div class="meta">${esc(spiega)}</div>
        </div>
        ${FRECCIA}
      </a>`;
    }
    h += `</div>`;
  }

  h += `<h2>Cosa fa quest'app, e cosa non fa</h2>
    <div class="card">
      <div class="meta"><b>Fa:</b> ti fa incontrare per condividere l'auto,
        e ti riporta due dati misurati da altri &mdash; quanta neve e' caduta
        secondo il modello meteo, e il grado di pericolo che ha emesso l'ente
        competente, con le esposizioni e le quote che indica lui.</div>
      <div class="meta" style="margin-top:10px"><b>Non fa:</b> non valuta la
        sicurezza di un itinerario, non dice se una gita e' adatta a te oggi,
        non incrocia il bollettino con l'esposizione della gita per dirti che
        &laquo;ti riguarda&raquo;. Non e' pudore: nessun modello meteo conosce
        la durezza degli strati, il limite fra neve nuova e vecchia, o quanto
        sfondi senza sci. Quelle cose si guardano sul posto, con la pala in
        mano, e si imparano a un corso.</div>
      <div class="meta" style="margin-top:10px"><b>E un passaggio in auto non
        e' una cordata:</b> chi guida non e' una guida, e la gita &mdash; con
        chi farla, e se farla &mdash; resta una decisione tua.</div>
    </div>
    </div>`;
  el.innerHTML = h;
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
          ${rigaEsperienza(u.autore)}
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

/* Un menu a tendina costruito dal vocabolario che manda il server: le
   etichette stanno in app/esperienza.py, in un posto solo. */
function scelta(id, voci, valore) {
  const opzioni = Object.entries(voci || {}).map(([k, testo]) =>
    `<option value="${esc(k)}" ${k === valore ? "selected" : ""}>${esc(testo)}</option>`);
  return `<select id="${id}">
    <option value="" ${!valore ? "selected" : ""}>non dichiaro</option>
    ${opzioni.join("")}</select>`;
}

VISTE.profilo = async function () {
  PROFILO = await api("/profilo");
  const VOC = PROFILO.vocabolario || {};
  const mie = await api("/mie");

  let h = `<div class="wrap"><h1>Profilo</h1>
    <div class="hint">Le preferenze si salvano una volta: dopo, pubblicare
      un'uscita sono due tap.</div>
    <div class="card" style="margin:12px var(--lato) 18px">
      <div class="hint">Come ti vedono gli altri</div>
      <div class="esperienza${PROFILO.esperienza_dichiarata ? "" : " assente"}"
        style="margin-top:4px">${esc(PROFILO.esperienza)}</div>
    </div>
    <div class="gruppo" style="margin-bottom:18px">
      <div class="voce" onclick="vai('emergenza')">
        <div class="corpo">
          <div class="titolo" style="font-size:15.5px">Emergenza</div>
          <div class="meta">Coordinate da dettare al 112, ripari vicini.
            Funziona senza rete.</div>
        </div>
        ${FRECCIA}
      </div>
      <div class="voce" onclick="vai('sapere')">
        <div class="corpo">
          <div class="titolo" style="font-size:15.5px">Sapere e utilita'</div>
          <div class="meta">Bollettini ufficiali, la scala del pericolo, dove
            si impara. E cosa fa quest'app, e cosa non fa.</div>
        </div>
        ${FRECCIA}
      </div>
    </div>
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

    <h2 style="margin-top:26px">La mia esperienza</h2>
    <div class="hint">Facoltativo, e nessuno verifica niente. Serve perche' chi
      sale in macchina con te sappia con chi va, invece di scoprirlo al
      parcheggio. Se lasci tutto vuoto, sulle tue uscite comparira'
      &laquo;esperienza non dichiarata&raquo;.</div>
    <label>Da quanti inverni fai scialpinismo</label>
    <input type="number" id="inverni" min="0" max="60" placeholder="non dichiaro"
      value="${PROFILO.inverni ?? ""}">
    <label>Corsi</label>
    ${scelta("formazione", VOC.formazione, PROFILO.formazione)}
    <label>Difficolta' che frequento di solito</label>
    ${scelta("difficolta_abituale", VOC.difficolta, PROFILO.difficolta_abituale)}
    <label>ARTVA, pala e sonda</label>
    <select id="artva">
      <option value="" ${PROFILO.artva === null || PROFILO.artva === undefined ? "selected" : ""}>non dichiaro</option>
      <option value="1" ${PROFILO.artva === true ? "selected" : ""}>li ho</option>
      <option value="0" ${PROFILO.artva === false ? "selected" : ""}>non li ho</option>
    </select>
    <div id="blocco-prova">
      <label>Ultima prova di ricerca con l'ARTVA</label>
      ${scelta("artva_prova", VOC.artva_prova, PROFILO.artva_prova)}
      <div class="hint">Avere l'ARTVA e saperlo usare sono due cose diverse:
        per questo la domanda e' quando l'hai provato, non se lo sai usare.</div>
    </div>

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
        ${rigaEsperienza(m.uscita.autore)}
        <span class="badge-tipo t-${m.uscita.tipo}">${m.uscita.tipo}</span>
        <div class="meta">${esc(m.motivo)}</div></div>`).join("")}
      ${u.stato === "aperta" ? `<button class="secondario" style="margin-top:10px"
        onclick="chiudi(${u.id})">Chiudi</button>` : ""}
    </div>`;
  }
  h += `<h2>Il mio diario</h2>
    <div class="hint" style="margin-bottom:8px">Le gite che hai segnato come
      fatte. Lo vedi solo tu: non entra nel riassunto della tua esperienza e
      non compare sulle tue uscite.</div>
    <div id="diario"><div class="hint">Carico...</div></div>`;
  h += `</div>`;
  el.innerHTML = h;

  disegnaDiario();

  // a chi dichiara di non avere l'ARTVA non si chiede quando l'ha provato:
  // sarebbe una domanda senza senso, e il server la scarterebbe comunque
  const selArtva = document.getElementById("artva");
  const bloccoProva = document.getElementById("blocco-prova");
  const mostraProva = () => { bloccoProva.hidden = selArtva.value === "0"; };
  selArtva.addEventListener("change", mostraProva);
  mostraProva();

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
        inverni: valoreNumero("inverni"),
        formazione: valore("formazione"),
        difficolta_abituale: valore("difficolta_abituale"),
        artva: valore("artva") === null ? null : valore("artva") === "1",
        artva_prova: valore("artva_prova"),
      }),
    });
    haptic();
    // si ridisegna: cosi' la riga "come ti vedono gli altri" mostra subito
    // quello che si e' appena salvato, invece di restare indietro
    vai("profilo");
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
    mostraFasciaSimulazione(CONFIG.simulazione);
    try { PROFILO = await api("/profilo"); } catch (e) { /* fuori da Telegram */ }
    vai("weekend");
  } catch (e) {
    el.innerHTML = `<div class="wrap"><div class="vuoto">
      Non riesco a contattare il server.<br>${esc(e.message)}</div></div>`;
  }
})();
