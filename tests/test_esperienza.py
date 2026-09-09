"""L'esperienza dichiarata: come si normalizza e come si riassume.

Non e' un filtro e non blocca niente: e' quello che una persona scrive di se'
e che gli altri vedono prima di accordarsi per un passaggio. Questi test
tengono ferme due cose: che dal modulo non entrino valori inventati, e che
chi non dichiara niente si veda comunque - in silenzio sarebbe peggio che non
chiederlo affatto.
"""
from __future__ import annotations

from types import SimpleNamespace

from app import esperienza as esp


def u(**kw):
    base = dict(inverni=None, formazione=None, difficolta_abituale=None,
                artva=None, artva_prova=None)
    base.update(kw)
    return SimpleNamespace(**base)


# ----------------------------------------------------------- normalizzazione


def test_pulisci_scarta_i_valori_non_previsti():
    p = esp.pulisci({"formazione": "maestro di sci", "difficolta_abituale": "XX",
                     "artva": "forse", "inverni": "tanti"})
    assert p == {"inverni": None, "formazione": None, "difficolta_abituale": None,
                 "artva": None, "artva_prova": None}


def test_pulisci_tiene_i_valori_buoni():
    p = esp.pulisci({"inverni": "6", "formazione": "corso",
                     "difficolta_abituale": "BSA", "artva": True,
                     "artva_prova": "stagione"})
    assert p["inverni"] == 6
    assert p["formazione"] == "corso"
    assert p["difficolta_abituale"] == "BSA"
    assert p["artva"] is True and p["artva_prova"] == "stagione"


def test_inverni_assurdi_valgono_non_dichiarato():
    assert esp.pulisci({"inverni": 500})["inverni"] is None
    assert esp.pulisci({"inverni": -3})["inverni"] is None


def test_senza_artva_la_prova_non_ha_senso():
    """Se dichiari di non averlo, 'ultima prova: quest'inverno' e' incoerente."""
    p = esp.pulisci({"artva": False, "artva_prova": "stagione"})
    assert p["artva"] is False
    assert p["artva_prova"] is None


# ------------------------------------------------------------------ riassunto


def test_chi_non_dichiara_niente_si_vede_lo_stesso():
    assert esp.riassunto(u()) == esp.NON_DICHIARATA
    assert esp.dichiarata(u()) is False


def test_riassunto_completo():
    r = esp.riassunto(u(inverni=6, formazione="corso", difficolta_abituale="BSA",
                        artva=True, artva_prova="stagione"))
    assert "6 inverni" in r
    assert "corso valanghe" in r
    assert "BSA" in r
    assert "ARTVA, prova quest'inverno" in r


def test_il_caso_che_conta_si_legge_a_colpo_docchio():
    """Primo inverno, nessun corso, niente ARTVA: deve saltare all'occhio."""
    r = esp.riassunto(u(inverni=0, formazione="nessuna", artva=False))
    assert "prima stagione" in r
    assert "nessun corso" in r
    assert "senza ARTVA" in r
    assert esp.dichiarata(u(artva=False)) is True


def test_artva_senza_prova_non_promette_nulla():
    r = esp.riassunto(u(artva=True))
    assert "ARTVA" in r
    assert "prova" not in r  # non inventiamo un allenamento che non c'e'


def test_un_inverno_solo_al_singolare():
    assert "1 inverno" in esp.riassunto(u(inverni=1))
    assert "1 inverni" not in esp.riassunto(u(inverni=1))
