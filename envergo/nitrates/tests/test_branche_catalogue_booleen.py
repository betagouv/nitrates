"""Edition d'une branche sous un gate catalogue BOOLEEN : la valeur saisie
`true`/`false` (toute casse) doit etre persistee en VRAI booleen, meme si
l'ancienne valeur etait une string.

Regression du bug PAR Grand Est : les gates `zone_grand_est_1/2`, `zone_note_5`,
etc. (resolveurs SIG renvoyant un bool) avaient des branches keyees sur une
string ('en_zge2', 'False'...). L'editeur preservait le type de l'ancienne
valeur -> impossible de corriger en booleen via l'UI. On force desormais la
coercion booleenne pour ces noeuds, et UNIQUEMENT pour eux (pas les
formulaires a valeur 'Non', pas les catalogue_parametre a etiquette).
"""

import textwrap

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from envergo.nitrates.models import DecisionTree

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_nitrates")]


@pytest.fixture(autouse=True)
def _purge():
    DecisionTree.objects.all().delete()


@pytest.fixture
def staff_user(db):
    User = get_user_model()
    return User.objects.create_user(
        email="staff@test.local", name="Staff", password="x", is_staff=True
    )


def _make_draft(make_active_tree, yaml_text):
    active = make_active_tree(yaml_text)
    return DecisionTree.objects.create(
        name=active.name,
        status=DecisionTree.STATUS_DRAFT,
        contenu=active.contenu,
        contenu_yaml_brut=active.contenu_yaml_brut,
        parent=active,
    )


@pytest.fixture
def draft_gate_zge2_string(make_active_tree):
    """Gate catalogue booleen (reference zone_grand_est_2) dont la branche est
    keyee sur une STRING 'en_zge2' -- exactement le bug a corriger."""
    return _make_draft(
        make_active_tree,
        textwrap.dedent(
            """\
            metadata:
              version: "0.0.1-test"
            arbre:
              noeud:
                type_noeud: "catalogue"
                id: "n_gate"
                champ: "zone_grand_est_2"
                reference: "zone_grand_est_2"
                source: "sig"
                branches:
                  - valeur: "en_zge2"
                    libelle: "en_zge2"
                    regle:
                      id: "r_vigne"
                      type: "interdiction"
            """
        ),
    )


@pytest.fixture
def draft_formulaire_non(make_active_tree):
    """Noeud formulaire dont une branche a la valeur 'Non' (libelle metier,
    PAS un booleen). Ne doit JAMAIS etre coerce en False."""
    return _make_draft(
        make_active_tree,
        textwrap.dedent(
            """\
            metadata:
              version: "0.0.1-test"
            arbre:
              noeud:
                type_noeud: "formulaire"
                niveau: "complement"
                id: "q_plan"
                texte: "Plan d'epandage ?"
                champ: "plan_epandage"
                branches:
                  - valeur: "Non"
                    libelle: "Non"
                    regle:
                      id: "r_non"
                      type: "interdiction"
            """
        ),
    )


def _post_edit(client, tree, parent_path, ancienne_valeur, nouvelle_valeur):
    url = (
        reverse("nitrates_admin_yaml_edit_branche", kwargs={"tree_pk": tree.pk})
        + f"?path={parent_path}&valeur={ancienne_valeur}"
    )
    return client.post(
        url,
        data={
            "path": parent_path,
            "valeur": ancienne_valeur,
            "valeur_new": nouvelle_valeur,
            "libelle": "En Zone Grand Est 2",
        },
    )


def _branche_valeur(tree, parent_id):
    """Recharge le tree et renvoie la valeur de la 1re branche du noeud."""
    tree.refresh_from_db()

    def find(node):
        if isinstance(node, dict):
            if node.get("id") == parent_id:
                return node
            for v in node.values():
                r = find(v)
                if r:
                    return r
        elif isinstance(node, list):
            for v in node:
                r = find(v)
                if r:
                    return r

    n = find(tree.contenu)
    return n["branches"][0]["valeur"]


def test_gate_booleen_saisie_true_persiste_un_vrai_booleen(
    client, staff_user, draft_gate_zge2_string
):
    """Branche string 'en_zge2' sous gate booleen, on saisit 'true' ->
    la valeur persistee doit etre le booleen True (pas la string 'True')."""
    client.force_login(staff_user)
    resp = _post_edit(client, draft_gate_zge2_string, "n_gate", "en_zge2", "true")
    assert resp.status_code in (200, 204), resp.content[:500]

    val = _branche_valeur(draft_gate_zge2_string, "n_gate")
    assert val is True, f"attendu booleen True, obtenu {val!r} ({type(val).__name__})"


@pytest.mark.parametrize("saisie", ["true", "True", "TRUE"])
def test_gate_booleen_true_insensible_casse(
    client, staff_user, draft_gate_zge2_string, saisie
):
    client.force_login(staff_user)
    resp = _post_edit(client, draft_gate_zge2_string, "n_gate", "en_zge2", saisie)
    assert resp.status_code in (200, 204), resp.content[:500]
    assert _branche_valeur(draft_gate_zge2_string, "n_gate") is True


def test_formulaire_valeur_non_n_est_pas_coercee_en_booleen(
    client, staff_user, draft_formulaire_non
):
    """Sur un noeud formulaire, 'Non' reste la string 'Non' : on ne doit pas
    la transformer en False (ce serait casser le routage du formulaire)."""
    client.force_login(staff_user)
    # On renomme 'Non' -> 'Non' (no-op) : doit rester une string.
    resp = _post_edit(client, draft_formulaire_non, "q_plan", "Non", "Non")
    assert resp.status_code in (200, 204), resp.content[:500]
    val = _branche_valeur(draft_formulaire_non, "q_plan")
    assert val == "Non" and isinstance(
        val, str
    ), f"attendu string 'Non', obtenu {val!r}"
