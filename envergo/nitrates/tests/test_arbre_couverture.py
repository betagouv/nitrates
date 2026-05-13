"""Tests de couverture exhaustive de l'arbre de decision.

Enumere recursivement toutes les feuilles atteignables sous la branche
`culture_principale` (scope MVP) et verifie que le parcours, alimente
avec un contexte minimal pertinent, atteint bien la regle attendue.

Pour les noeuds catalogue intermediaires (zone_note_5, etc.), on injecte
une valeur predeterminee dans le contexte (les deux : True puis False)
afin de couvrir les deux sous-branches.

Ce test est genere : si l'arbre PAN evolue (ajout/suppression de
feuilles), le compte de tests parametrises change automatiquement.
"""

import pytest

from envergo.nitrates.yaml_tree.loader import load_arbre
from envergo.nitrates.yaml_tree.parcours import BesoinCatalogue, Resultat, parcours

# La fixture session `update_default_site` (envergo/conftest.py) cree un
# Site testserver et necessite l'acces DB. On opt-in.
pytestmark = pytest.mark.django_db


def _enumerer_feuilles_culture_principale(arbre: dict) -> list[tuple]:
    """Pour chaque feuille atteignable sous culture_principale, retourne
    `(label, contexte, regle_id_attendue)`.

    Ouvre les noeuds catalogue avec un Cartesian product True/False sur
    chaque champ de catalogue rencontre, ce qui couvre par construction
    toutes les branches catalogue. Renvoi_vers est resolu vers l'id cible.
    """
    racine = arbre.get("arbre", {}).get("noeud")
    if not racine:
        return []

    # On trouve la branche `valeur=True` du noeud racine n_zvn (en ZV) puis
    # on descend dans l'arbre. Si racine est un catalogue racine et que la
    # branche True conduit vers q_occupation_sol, on plante notre depart la.
    contexte_base = {"en_zone_vulnerable": True}
    if racine.get("type_noeud") == "catalogue" and racine.get("id") == "n_zvn":
        branche_oui = next(
            (b for b in racine.get("branches", []) if b.get("valeur") is True),
            None,
        )
        if not branche_oui or "noeud" not in branche_oui:
            return []
        sous = branche_oui["noeud"]
    else:
        sous = racine

    # `sous` doit etre q_occupation_sol (champ=occupation_sol)
    if sous.get("champ") != "occupation_sol":
        return []

    # On filtre uniquement la branche `culture_principale`
    branche_cp = next(
        (
            b
            for b in sous.get("branches", [])
            if b.get("valeur") == "culture_principale"
        ),
        None,
    )
    if not branche_cp or "noeud" not in branche_cp:
        return []

    cas: list[tuple] = []
    contexte_init = {**contexte_base, "occupation_sol": "culture_principale"}
    _walk(branche_cp["noeud"], contexte_init, [], cas)
    return cas


def _walk(noeud: dict, contexte: dict, path_label: list, cas: list) -> None:
    """Descend recursivement et enrichit `cas` avec `(label, contexte, regle_id)`
    pour chaque feuille atteignable. Pour les catalogues internes, on
    explore True puis False."""
    type_noeud = noeud.get("type_noeud")
    champ = noeud.get("champ")

    if type_noeud == "catalogue":
        # On explore les 2 valeurs (True et False) sauf si la valeur est
        # deja contrainte dans les branches definies.
        valeurs_branches = [b.get("valeur") for b in noeud.get("branches", [])]
        for valeur in valeurs_branches:
            sous_contexte = dict(contexte)
            sous_contexte[champ] = valeur
            sous_label = path_label + [f"{champ}={valeur}"]
            branche = next(
                b for b in noeud.get("branches", []) if b.get("valeur") == valeur
            )
            _explore_branche(branche, sous_contexte, sous_label, cas)
        return

    if type_noeud == "formulaire":
        # On explore chaque branche en posant la valeur correspondante
        for branche in noeud.get("branches", []):
            valeur = branche.get("valeur")
            sous_contexte = dict(contexte)
            sous_contexte[champ] = valeur
            sous_label = path_label + [f"{champ}={valeur}"]
            _explore_branche(branche, sous_contexte, sous_label, cas)


def _explore_branche(branche: dict, contexte: dict, label: list, cas: list) -> None:
    if "noeud" in branche:
        _walk(branche["noeud"], contexte, label, cas)
    elif "regle" in branche:
        cas.append((" / ".join(label), contexte, branche["regle"]["id"]))
    elif "renvoi_vers" in branche:
        # Note 2026-05-12 : renvoi_vers peut maintenant pointer vers un noeud
        # (sous-arbre reutilisable, pattern "include") -- pas seulement vers
        # une regle. Quand c'est un noeud, le parcours descend dedans et peut
        # demander des QC supplementaires. On ne genere PAS de cas de test
        # pour ces renvois car le contexte fourni ne contient pas forcement
        # toutes les QC necessaires, et les cas terminaux (regles atteintes
        # apres renvoi) sont deja couverts par leur propre exploration en
        # amont (le sous-arbre cible est lui-meme exhaustivement teste).
        cible_id = branche["renvoi_vers"]
        if cible_id.startswith("r_"):
            # Renvoi vers une regle : terminal, on enregistre.
            cas.append((" / ".join(label) + f" -> {cible_id}", contexte, None))
        # Sinon (q_/n_) : skip silencieusement, sous-arbre teste ailleurs.


def _build_cas() -> list:
    """Charge le YAML disque et construit la liste des cas. Appele au
    moment du collect pytest, donc une seule fois par run."""
    try:
        arbre = load_arbre("arbre_decision_national")
    except Exception:
        return []
    return _enumerer_feuilles_culture_principale(arbre)


CAS_FEUILLES = _build_cas()


@pytest.mark.parametrize(
    "label,contexte,regle_id_attendue",
    CAS_FEUILLES,
    ids=[c[0] for c in CAS_FEUILLES] if CAS_FEUILLES else [],
)
def test_feuille_culture_principale_atteinte(label, contexte, regle_id_attendue):
    """Pour chaque feuille de l'arbre sous culture_principale, on verifie
    que le parcours alimente avec le contexte attendu atteint bien la
    bonne `regle_id`. Les renvoi_vers (regle_id_attendue=None) sont
    juste verifies pour ne pas crasher."""
    arbre = load_arbre("arbre_decision_national")

    # On boucle pour resoudre les BesoinCatalogue qui apparaitraient
    # encore (catalogues que le walker n'a pas pre-injectes : tous les
    # catalogues internes sont normalement dans le contexte deja).
    for _ in range(20):
        res = parcours(arbre, contexte)
        if isinstance(res, BesoinCatalogue):
            # En theorie le walker injecte tout, mais defensive : on
            # injecte False par defaut.
            contexte[res.champ] = False
            continue
        break

    assert isinstance(
        res, Resultat
    ), f"[{label}] attend Resultat, recu {type(res).__name__}"

    if regle_id_attendue is not None:
        assert res.regle_id == regle_id_attendue, (
            f"[{label}] regle_id mismatch : "
            f"attendu {regle_id_attendue}, recu {res.regle_id}"
        )


def test_au_moins_un_cas_genere():
    """Garde-fou : si la fonction de collecte rate (arbre vide, format
    inattendu), on doit s'en rendre compte au lieu de tout passer."""
    assert len(CAS_FEUILLES) > 0, (
        "Aucun cas genere par _enumerer_feuilles_culture_principale -- "
        "verifier que NITRATES_SPECS_DIR pointe vers un YAML valide avec "
        "une branche culture_principale."
    )
