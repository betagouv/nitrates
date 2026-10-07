"""Commandes d'audit et de nettoyage des données éditées dans l'admin.

audit_residus_texte_condition / nettoyer_residus_calculatrice (#218, #219),
rapport_resolution_pc (#147), liens_references (#467).
"""

import io

import pytest
import yaml as pyyaml
from django.core.management import call_command

from envergo.nitrates.models import (
    CodePrescription,
    ContenuRichDSFR,
    DecisionTree,
    LienReference,
)

pytestmark = pytest.mark.django_db

ARBRE_AVEC_RESIDU = """\
arbre:
  noeud:
    id: n_racine
    champ: occupation_sol
    branches:
    - valeur: a
      regle:
        id: r_residu
        type: interdiction
        composant: calendrier_dynamique_couvert
        inputs_requis:
        - date_semis
        texte_condition: herite du calendrier
        periodes:
        - debut: 01-01
          fin: 01-31
          condition: date_semis
          masque: true
    - valeur: b
      regle:
        id: r_saine
        type: interdiction
        texte_condition: justification voulue
        code_prescription:
        - pc1
"""


def _run(*args, **kwargs):
    out = io.StringIO()
    call_command(*args, stdout=out, stderr=io.StringIO(), **kwargs)
    return out.getvalue()


def _regle(contenu, regle_id):
    branches = contenu["arbre"]["noeud"]["branches"]
    return next(b["regle"] for b in branches if b["regle"]["id"] == regle_id)


# --- audit_residus_texte_condition ------------------------------------------


def test_audit_signale_le_residu_et_ses_champs(make_active_tree):
    make_active_tree(ARBRE_AVEC_RESIDU)

    out = _run("audit_residus_texte_condition")

    assert "[1 RESIDU(S)]" in out
    assert "r_residu" in out
    assert "inputs_requis, texte_condition, condition/masque periode" in out
    assert "r_saine" not in out
    assert "Total : 1 residu(s)" in out


def test_audit_arbre_propre_et_exclusions(make_active_tree):
    make_active_tree(ARBRE_AVEC_RESIDU, name="PAR HdF")
    propre = pyyaml.safe_load(ARBRE_AVEC_RESIDU)
    propre["arbre"]["noeud"]["branches"].pop(0)
    DecisionTree.objects.create(
        name="brouillon", status=DecisionTree.STATUS_DRAFT, contenu=propre
    )

    out = _run("audit_residus_texte_condition")
    assert "Aucun residu calculatrice" in out

    out = _run("audit_residus_texte_condition", "--all", "--inclure-hdf")
    assert "PAR HdF" in out
    assert "[OK]" in out and "brouillon" in out


# --- nettoyer_residus_calculatrice ------------------------------------------


def test_nettoyer_dry_run_ne_sauve_rien(make_active_tree):
    tree = make_active_tree(ARBRE_AVEC_RESIDU)

    out = _run("nettoyer_residus_calculatrice")

    tree.refresh_from_db()
    assert _regle(tree.contenu, "r_residu")["composant"]
    assert "DRY-RUN : 1 regle(s)" in out


def test_nettoyer_apply_purge_contenu_et_yaml_brut(make_active_tree):
    tree = make_active_tree(ARBRE_AVEC_RESIDU)

    out = _run("nettoyer_residus_calculatrice", "--apply")

    tree.refresh_from_db()
    for contenu in (tree.contenu, pyyaml.safe_load(tree.contenu_yaml_brut)):
        residu = _regle(contenu, "r_residu")
        assert residu == {
            "id": "r_residu",
            "type": "interdiction",
            "periodes": [{"debut": "01-01", "fin": "01-31"}],
        }
        # La justification volontaire d'une règle saine est conservée.
        assert _regle(contenu, "r_saine")["texte_condition"] == "justification voulue"
    assert "1 regle(s) nettoyee(s)" in out

    assert "Aucun residu" in _run("nettoyer_residus_calculatrice", "--apply")


def test_nettoyer_exclut_par_hdf_sauf_option(make_active_tree):
    tree = make_active_tree(ARBRE_AVEC_RESIDU, name="PAR HdF")

    _run("nettoyer_residus_calculatrice", "--apply")
    tree.refresh_from_db()
    assert "composant" in _regle(tree.contenu, "r_residu")

    _run("nettoyer_residus_calculatrice", "--apply", "--inclure-hdf")
    tree.refresh_from_db()
    assert "composant" not in _regle(tree.contenu, "r_residu")


# --- rapport_resolution_pc --------------------------------------------------


def test_rapport_resolution_pc_compte_les_regles_avec_pc(make_active_tree):
    make_active_tree(ARBRE_AVEC_RESIDU)

    out = _run("rapport_resolution_pc", "--tous")

    assert "r_saine : pc1" in out
    assert "hors zone spécifique" in out
    assert "1 règle(s) avec PC" in out


def test_rapport_resolution_pc_masque_les_identites(make_active_tree):
    make_active_tree(ARBRE_AVEC_RESIDU)
    tous = _run("rapport_resolution_pc", "--tous")
    filtre = _run("rapport_resolution_pc")
    assert len(filtre) <= len(tous)
    assert "1 règle(s) avec PC" in filtre


# --- liens_references -------------------------------------------------------


@pytest.fixture
def liens():
    LienReference.objects.all().delete()
    LienReference.objects.create(identifiant="lien-utilise", url="https://a.example")
    LienReference.objects.create(identifiant="lien-mort", url="https://b.example")
    ContenuRichDSFR.objects.create(
        cle="page_test",
        libelle_admin="Page test",
        blocs=[{"type": "lien", "lien_ref": "lien-utilise"}],
    )
    pc = CodePrescription.objects.filter(blocs__isnull=False).first()
    if pc is None:
        pc = CodePrescription.objects.create(identifiant="pc_test_liens")
    pc.blocs = [{"enfants": [{"lien_ref": "lien-absent"}]}]
    pc.save()
    return pc


def test_liens_references_liste(liens):
    out = _run("liens_references")
    assert "lien-utilise → https://a.example" in out
    assert "2 lien(s)." in out


def test_liens_references_usages_et_orphelins(liens):
    out = _run("liens_references", "--usages")

    assert "ContenuRich:page_test" in out
    assert "lien-mort → https://b.example\n    AUCUN USAGE" in out
    assert "lien-absent → ORPHELIN" in out
    assert f"PC:{liens.identifiant}" in out
