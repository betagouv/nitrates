"""Edition d'une regle : dropdowns fermes pour code_prescription et note.

Les champs `code_prescription` et `note` etaient en texte libre, ce qui
permettait de creer des slugs inexistants (typos `pc4` vs `pc_4`).
On les remplace par des <select> alimentes depuis referentiels.yaml.
Une option vide ("— (aucun)") permet de laisser la regle sans code/note.
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


@pytest.fixture
def draft_with_regle(make_active_tree):
    yaml_text = textwrap.dedent(
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
                regle:
                  id: "r_main"
                  type: "interdiction"
                  code_prescription: "pc1"
                  note: "note_5"
        """
    )
    active = make_active_tree(yaml_text)
    return DecisionTree.objects.create(
        name=active.name,
        status=DecisionTree.STATUS_DRAFT,
        contenu=active.contenu,
        contenu_yaml_brut=active.contenu_yaml_brut,
        parent=active,
    )


def _edit_url(tree, parent_path, valeur):
    return (
        reverse("nitrates_admin_yaml_edit_regle", kwargs={"tree_pk": tree.pk})
        + f"?path={parent_path}&valeur={valeur}"
    )


def test_code_prescription_is_select_with_referentiel_slugs(
    client, staff_user, draft_with_regle
):
    """Le champ code_prescription doit etre un <select> ferme alimente
    depuis referentiels.yaml::codes_prescription."""
    client.force_login(staff_user)
    resp = client.get(_edit_url(draft_with_regle, "n_root", "True"))
    assert resp.status_code == 200, resp.content[:500]
    body = resp.content.decode()

    assert (
        '<select name="code_prescription"' in body
    ), "code_prescription doit etre un <select>"
    assert (
        '<input type="text"\n               name="code_prescription"' not in body
    ), "code_prescription ne doit plus etre un <input>"

    # Plusieurs slugs canoniques (pc1, pc2, pc3...) doivent etre presents
    pc_count = sum(
        1 for s in ("pc1", "pc2", "pc3", "pc4", "pc5") if f'value="{s}"' in body
    )
    assert (
        pc_count >= 3
    ), f"select code_prescription doit lister >=3 pcN, trouve {pc_count}"

    # La valeur courante (pc1) doit etre selected
    assert 'value="pc1"' in body and "selected" in body


def test_code_prescription_has_empty_option(client, staff_user, draft_with_regle):
    """L'option `<option value="">` doit etre presente : toutes les regles
    n'ont pas de code_prescription, on doit pouvoir le laisser vide."""
    client.force_login(staff_user)
    body = client.get(_edit_url(draft_with_regle, "n_root", "True")).content.decode()
    # Bloc du <select code_prescription>
    select_start = body.find('<select name="code_prescription"')
    select_end = body.find("</select>", select_start)
    select_html = body[select_start:select_end]
    assert 'value=""' in select_html, "option vide manquante (— aucun)"


def test_note_is_select_with_referentiel_slugs(client, staff_user, draft_with_regle):
    """Le champ note doit etre un <select> ferme alimente depuis
    referentiels.yaml::notes."""
    client.force_login(staff_user)
    body = client.get(_edit_url(draft_with_regle, "n_root", "True")).content.decode()

    assert '<select name="note"' in body
    # Les notes canoniques note_1..note_N doivent etre presentes
    note_count = sum(
        1
        for s in ("note_1", "note_2", "note_3", "note_4", "note_5")
        if f'value="{s}"' in body
    )
    assert note_count >= 3, f"select note doit lister >=3 note_N, trouve {note_count}"

    # La valeur courante (note_5) doit etre selected
    assert 'value="note_5"' in body


def test_note_has_empty_option(client, staff_user, draft_with_regle):
    client.force_login(staff_user)
    body = client.get(_edit_url(draft_with_regle, "n_root", "True")).content.decode()
    select_start = body.find('<select name="note"')
    select_end = body.find("</select>", select_start)
    select_html = body[select_start:select_end]
    assert 'value=""' in select_html, "option vide manquante (— aucune)"


def test_options_have_title_for_long_text(client, staff_user, draft_with_regle):
    """Les options des selects code_prescription et note doivent exposer
    le texte long en attribut title (pour le hover navigateur)."""
    client.force_login(staff_user)
    body = client.get(_edit_url(draft_with_regle, "n_root", "True")).content.decode()
    # Pour code_prescription : texte_court attendu en title
    select_start = body.find('<select name="code_prescription"')
    select_end = body.find("</select>", select_start)
    pc_html = body[select_start:select_end]
    assert 'title="' in pc_html, "options code_prescription doivent avoir un title"

    # Pour note : condition_declenchement attendu en title
    select_start = body.find('<select name="note"')
    select_end = body.find("</select>", select_start)
    note_html = body[select_start:select_end]
    assert 'title="' in note_html, "options note doivent avoir un title"


def test_options_show_libelle_after_slug(client, staff_user, draft_with_regle):
    """Affichage `pcN — mots_cles` / `note_N — libelle_court` pour lisibilite."""
    client.force_login(staff_user)
    body = client.get(_edit_url(draft_with_regle, "n_root", "True")).content.decode()
    assert "—" in body, "le pattern `slug — libelle` doit apparaitre dans les options"
