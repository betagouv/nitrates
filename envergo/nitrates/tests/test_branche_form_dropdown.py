"""Edition d'une branche : dropdown ferme pour les niveaux mappes au referentiel.

Quand le parent d'une branche est un noeud formulaire de niveau
`type_fertilisant` ou `sous_culture`, le champ `valeur` rendu par
`EditBrancheView` doit etre un `<select>` ferme alimente depuis
`envergo/nitrates/specs/referentiels.yaml`. Pour les autres niveaux
(culture, complement, etc.) et les noeuds sans niveau, c'est un
`<input type=text>` libre comme avant.
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
def draft_type_fertilisant(make_active_tree):
    return _make_draft(
        make_active_tree,
        textwrap.dedent(
            """\
            metadata:
              version: "0.0.1-test"
            arbre:
              noeud:
                type_noeud: "catalogue"
                id: "n_root"
                champ: "en_zv"
                source: "sig"
                branches:
                  - valeur: true
                    noeud:
                      type_noeud: "formulaire"
                      niveau: "type_fertilisant"
                      id: "q_fert"
                      texte: "Quel fertilisant ?"
                      champ: "type_fertilisant"
                      branches:
                        - valeur: "type_0"
                          libelle: "Type 0"
                          regle:
                            id: "r_type0"
                            type: "interdiction"
            """
        ),
    )


@pytest.fixture
def draft_sous_culture(make_active_tree):
    return _make_draft(
        make_active_tree,
        textwrap.dedent(
            """\
            metadata:
              version: "0.0.1-test"
            arbre:
              noeud:
                type_noeud: "formulaire"
                niveau: "sous_culture"
                id: "q_sc"
                texte: "Quelle sous-culture ?"
                champ: "sous_culture"
                branches:
                  - valeur: "colza"
                    libelle: "Colza"
                    regle:
                      id: "r_colza"
                      type: "interdiction"
            """
        ),
    )


@pytest.fixture
def draft_culture_libre(make_active_tree):
    """Niveau `culture` -- pas mappe au referentiel -> input libre."""
    return _make_draft(
        make_active_tree,
        textwrap.dedent(
            """\
            metadata:
              version: "0.0.1-test"
            arbre:
              noeud:
                type_noeud: "formulaire"
                niveau: "culture"
                id: "q_culture"
                texte: "Quelle culture ?"
                champ: "occupation_sol"
                branches:
                  - valeur: "culture_hiver"
                    libelle: "Culture d'hiver"
                    regle:
                      id: "r_ch"
                      type: "interdiction"
            """
        ),
    )


def _edit_url(tree, parent_path, valeur):
    return (
        reverse("nitrates_admin_yaml_edit_branche", kwargs={"tree_pk": tree.pk})
        + f"?path={parent_path}&valeur={valeur}"
    )


def test_type_fertilisant_renders_closed_select_with_referentiel_slugs(
    client, staff_user, draft_type_fertilisant
):
    """Edition d'une branche de niveau type_fertilisant -> <select> ferme,
    pas d'<input type=text> pour le champ valeur."""
    client.force_login(staff_user)
    resp = client.get(_edit_url(draft_type_fertilisant, "n_root/q_fert", "type_0"))
    assert resp.status_code == 200, resp.content[:500]
    body = resp.content.decode()

    # Le champ valeur doit etre un <select>, pas un <input type=text>
    assert (
        '<select name="valeur_new"' in body
    ), "valeur doit etre un select ferme pour niveau type_fertilisant"
    assert (
        '<input type="text" name="valeur_new"' not in body
    ), "valeur doit etre un select ferme, pas un input libre"

    # Les slugs canoniques du referentiel (type_Ia, type_Ib, type_II...)
    # doivent etre presents en options. La selection courante (type_0)
    # doit etre marquee selected.
    assert (
        'value="type_0"' in body and "selected" in body
    ), "la valeur courante type_0 doit etre selected"
    # Au moins 2 autres slugs du referentiel : on n'asserte pas exactement
    # lesquels (le referentiel peut evoluer), juste qu'il y en a plusieurs.
    other_slugs_present = sum(
        1
        for s in ("type_Ia", "type_Ib", "type_II", "type_III", "type_I")
        if f'value="{s}"' in body
    )
    assert other_slugs_present >= 2, (
        f"select doit lister >=2 autres slugs du referentiel, trouve "
        f"{other_slugs_present}"
    )


def test_sous_culture_renders_closed_select(client, staff_user, draft_sous_culture):
    """Idem pour niveau sous_culture."""
    client.force_login(staff_user)
    resp = client.get(_edit_url(draft_sous_culture, "q_sc", "colza"))
    assert resp.status_code == 200, resp.content[:500]
    body = resp.content.decode()
    assert '<select name="valeur_new"' in body
    assert '<input type="text" name="valeur_new"' not in body
    # Plusieurs sous_cultures attendues depuis le referentiel.
    option_count = body.count("<option value=")
    assert (
        option_count >= 3
    ), f"select sous_culture doit avoir >=3 options, trouve {option_count}"


def test_culture_falls_back_to_free_input(client, staff_user, draft_culture_libre):
    """Niveau `culture` n'est pas mappe au referentiel : on garde l'input
    libre. C'est intentionnel -- la liste des cultures principales n'est
    pas figee."""
    client.force_login(staff_user)
    resp = client.get(_edit_url(draft_culture_libre, "q_culture", "culture_hiver"))
    assert resp.status_code == 200, resp.content[:500]
    body = resp.content.decode()
    # Input libre, pas de select sur valeur_new
    assert '<input type="text" name="valeur_new"' in body
    assert '<select name="valeur_new"' not in body


def test_select_options_include_libelle(client, staff_user, draft_type_fertilisant):
    """L'option du select doit etre lisible : `type_0 — Type 0` (slug + libelle
    court du referentiel). Permet au juriste de comprendre ce qu'il selectionne."""
    client.force_login(staff_user)
    body = client.get(
        _edit_url(draft_type_fertilisant, "n_root/q_fert", "type_0")
    ).content.decode()
    # Au moins une option avec le pattern "slug — libelle"
    assert (
        "—" in body
    ), "options du select doivent inclure le libelle apres un tiret cadratin"


def test_select_options_have_title_for_long_description(
    client, staff_user, draft_type_fertilisant
):
    """Pour aider la selection, on expose le libelle public (texte plus long)
    en attribut title de l'option -- le navigateur l'affiche au survol."""
    client.force_login(staff_user)
    body = client.get(
        _edit_url(draft_type_fertilisant, "n_root/q_fert", "type_0")
    ).content.decode()
    assert 'title="' in body, "options du select doivent avoir un title pour le hover"
