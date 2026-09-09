# Bozza di mail a Gulliver

Da mandare all'indirizzo della pagina contatti di gulliver.it.
Tienila corta: dall'altra parte ci sono persone, non un ufficio.

---

**Oggetto:** Progetto no-profit di car sharing per gite scialpinistiche nel Cuneese — richiesta di collaborazione

Buongiorno,

siamo un gruppo di scialpinisti della provincia di Cuneo. Stiamo sviluppando,
senza alcuno scopo di lucro, un piccolo servizio su Telegram che aiuta chi va
in gita a organizzare passaggi in auto condivisi: meno macchine sulle strade
delle valli, meno spese, meno inquinamento, e un modo per trovare compagni di
gita quando si è da soli.

Per farlo funzionare ci serve, per ogni itinerario, un minimo di dati
strutturati: nome, comune, coordinate del punto di partenza, quota,
dislivello, esposizione e difficoltà. Nient'altro: nessuna relazione, nessun
testo descrittivo, nessuna fotografia. Le vostre relazioni resterebbero dove
sono, e ogni itinerario nel nostro servizio rimanderebbe con un link diretto
alla pagina corrispondente su Gulliver, con l'attribuzione ben visibile.

Prima di procedere in qualunque modo, abbiamo preferito chiedervelo. Non
useremo i vostri contenuti senza il vostro consenso, e non abbiamo alcuna
intenzione di costruire qualcosa che vi sottragga visite: semmai il
contrario, dato che il nostro servizio manderebbe traffico verso di voi.

Se la cosa vi interessa, siamo disponibili a qualsiasi forma vi risulti più
comoda — un export una tantum, un accesso limitato, o anche solo un vostro
benestare su come procedere. Siamo altrettanto disponibili a mostrare il
progetto prima che sia pubblico e ad accogliere le condizioni che riterrete
opportune.

Se invece preferite di no, nessun problema: ci basta saperlo, e costruiremo
il nostro elenco per conto nostro.

Grazie per quello che fate, il sito è un punto di riferimento per tutti noi
da anni.

Un saluto,
Francesco — [nomi del gruppo]
[contatto]

---

## Se rispondono di sì

Chiedi il formato che è più comodo a loro (un CSV una tantum va benissimo) e
aggiungi un `importers/gulliver.py` che legge quel file. Il modello dati è già
pronto: `fonte="gulliver"`, `fonte_url` alla pagina dell'itinerario,
`licenza` e `autori` come concordato con loro.

## Se rispondono di no, o non rispondono

Non insistere e non prendere i dati lo stesso. Il catalogo si costruisce con
Camptocamp, Skitour, OSM e il seed manuale del gruppo — che tra l'altro dà
itinerari meglio selezionati, perché sono quelli che la gente fa davvero.
