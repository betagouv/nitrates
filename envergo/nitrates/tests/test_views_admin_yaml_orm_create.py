"""Tests création htmx d'objets ORM depuis l'éditeur YAML (issue #103)."""

import pytest
from django.urls import reverse

from envergo.nitrates.models import (
    BrancheCulturale,
    CategorieCulture,
    CodePrescription,
    Culture,
    DecisionTree,
    Fertilisant,
    NoteReglementaire,
)
from envergo.nitrates.views_admin_yaml_orm_create import _path_choices_for_test
from envergo.users.tests.factories import UserFactory

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_nitrates")]


# ─── _path_choices : extraction du contexte parent ──────────────────────────


ARBRE_MINI = {
    "arbre": {
        "noeud": {
            "id": "q_occupation_sol",
            "type_noeud": "formulaire",
            "champ": "occupation_sol",
            "branches": [
                {
                    "valeur": "culture_principale",
                    "noeud": {
                        "id": "q_categorie_culture",
                        "type_noeud": "formulaire",
                        "champ": "categorie_culture",
                        "branches": [
                            {
                                "valeur": "culture_printemps",
                                "noeud": {
                                    "id": "q_sous_culture",
                                    "type_noeud": "formulaire",
                                    "champ": "sous_culture",
                                    "branches": [],
                                },
                            }
                        ],
                    },
                }
            ],
        }
    }
}


def test_path_choices_racine():
    assert _path_choices_for_test(ARBRE_MINI, ("q_occupation_sol",)) == {}


def test_path_choices_un_niveau():
    assert _path_choices_for_test(
        ARBRE_MINI, ("q_occupation_sol", "q_categorie_culture")
    ) == {"occupation_sol": "culture_principale"}


def test_path_choices_deux_niveaux():
    choices = _path_choices_for_test(
        ARBRE_MINI,
        ("q_occupation_sol", "q_categorie_culture", "q_sous_culture"),
    )
    assert choices == {
        "occupation_sol": "culture_principale",
        "categorie_culture": "culture_printemps",
    }


def test_path_choices_chemin_invalide():
    assert _path_choices_for_test(ARBRE_MINI, ("inexistant",)) == {}


# ─── Endpoint orm-create GET (panel) ────────────────────────────────────────


@pytest.fixture
def tree():
    return DecisionTree.objects.create(
        name="Tree test #103",
        contenu={"arbre": {"noeud": {"id": "racine", "branches": []}}},
        status=DecisionTree.STATUS_DRAFT,
    )


def _login(client):
    user = UserFactory(is_staff=True, is_superuser=True)
    client.force_login(user)


def test_get_panel_note_simple(client, tree):
    _login(client)
    url = reverse("nitrates_admin_yaml_orm_create", kwargs={"model_key": "note"})
    resp = client.get(
        f"{url}?tree_pk={tree.pk}&parent_path=&target_select=%23test-select"
    )
    assert resp.status_code == 200
    assert b"Nouvelle note" in resp.content
    assert b"identifiant" in resp.content


def test_get_panel_modele_inconnu(client, tree):
    _login(client)
    url = reverse("nitrates_admin_yaml_orm_create", kwargs={"model_key": "yolo"})
    resp = client.get(f"{url}?tree_pk={tree.pk}")
    assert resp.status_code == 400


@pytest.mark.skip(
    reason=(
        "V1 #103 : creation Culture via panel desactivee, l'arbre "
        "n'expose pas de niveau categorie_culture distinct."
    )
)
def test_get_panel_culture_resout_fk_si_chemin_complet(client):
    """Si le chemin parent contient categorie_culture + occupation_sol,
    on doit pouvoir créer une Culture sans erreur."""
    _login(client)
    # On a besoin que les FK existent en DB.
    cat = CategorieCulture.objects.filter(identifiant="culture_principale").first()
    assert cat, "Pré-condition : seed culture_principale présent"
    branche = BrancheCulturale.objects.filter(identifiant="culture_printemps").first()
    assert branche, "Pré-condition : seed culture_printemps présent"

    tree = DecisionTree.objects.create(
        name="Tree culture #103",
        contenu=ARBRE_MINI,
        status=DecisionTree.STATUS_DRAFT,
    )
    url = reverse("nitrates_admin_yaml_orm_create", kwargs={"model_key": "culture"})
    path = "q_occupation_sol/q_categorie_culture/q_sous_culture"
    resp = client.get(
        f"{url}?tree_pk={tree.pk}&parent_path={path}&target_select=%23sel"
    )
    assert resp.status_code == 200
    # FK auto-résolues affichées dans le panel.
    content = resp.content.decode()
    assert "culture_printemps" in content


def test_get_panel_culture_bloque_si_fk_manquantes(client, tree):
    """Sans chemin parent qui résout les FK, on renvoie le panel bloqué."""
    _login(client)
    url = reverse("nitrates_admin_yaml_orm_create", kwargs={"model_key": "culture"})
    resp = client.get(f"{url}?tree_pk={tree.pk}&parent_path=&target_select=%23s")
    assert resp.status_code == 200
    assert b"Cr\xc3\xa9ation impossible" in resp.content


# ─── Endpoint orm-create POST (creation) ────────────────────────────────────


def test_post_note_cree_objet_en_db(client, tree):
    _login(client)
    url = reverse("nitrates_admin_yaml_orm_create", kwargs={"model_key": "note"})
    n_before = NoteReglementaire.objects.count()
    resp = client.post(
        url,
        {
            "tree_pk": tree.pk,
            "parent_path": "",
            "target_select": "#sel",
            "identifiant": "note_test_103",
            "libelle_court": "Test note",
            "condition_declenchement": "test",
        },
    )
    assert resp.status_code == 200
    assert NoteReglementaire.objects.count() == n_before + 1
    assert NoteReglementaire.objects.filter(identifiant="note_test_103").exists()
    # Le fragment success contient le script qui réinjecte l'option.
    assert b"note_test_103" in resp.content
    assert b"target-select" in resp.content


def test_post_sans_identifiant_renvoie_panel_avec_erreur(client, tree):
    _login(client)
    url = reverse("nitrates_admin_yaml_orm_create", kwargs={"model_key": "note"})
    resp = client.post(
        url,
        {
            "tree_pk": tree.pk,
            "parent_path": "",
            "target_select": "#sel",
            "identifiant": "",
            "libelle_court": "rien",
        },
    )
    assert resp.status_code == 422
    assert b"obligatoire" in resp.content


def test_post_identifiant_duplique_renvoie_erreur(client, tree):
    _login(client)
    # Pré-existant en DB (seedé).
    NoteReglementaire.objects.create(identifiant="note_test_dup", libelle_court="A")
    url = reverse("nitrates_admin_yaml_orm_create", kwargs={"model_key": "note"})
    resp = client.post(
        url,
        {
            "tree_pk": tree.pk,
            "parent_path": "",
            "target_select": "#sel",
            "identifiant": "note_test_dup",
            "libelle_court": "B",
        },
    )
    assert resp.status_code == 422


@pytest.mark.skip(reason="V1 #103 : creation Culture via panel desactivee")
def test_post_culture_avec_fk_resolues(client):
    """Création complète d'une Culture avec FK auto-résolues depuis le chemin."""
    _login(client)
    cat = CategorieCulture.objects.filter(identifiant="culture_principale").first()
    branche = BrancheCulturale.objects.filter(identifiant="culture_printemps").first()
    assert cat and branche

    tree = DecisionTree.objects.create(
        name="Tree cult create #103",
        contenu=ARBRE_MINI,
        status=DecisionTree.STATUS_DRAFT,
    )
    url = reverse("nitrates_admin_yaml_orm_create", kwargs={"model_key": "culture"})
    resp = client.post(
        url,
        {
            "tree_pk": tree.pk,
            "parent_path": "q_occupation_sol/q_categorie_culture/q_sous_culture",
            "target_select": "#sel",
            "identifiant": "culture_test_103",
            "libelle_public": "Culture test 103",
        },
    )
    assert resp.status_code == 200, resp.content
    obj = Culture.objects.get(identifiant="culture_test_103")
    assert obj.categorie == cat
    assert obj.branche_culturale == branche
    assert obj.occupation_sol == "culture_principale"


@pytest.mark.skip(reason="V1 #103 : creation Fertilisant via panel desactivee")
def test_post_fertilisant_avec_fk_resolue(client):
    """Création d'un Fertilisant avec FK categorie auto-résolue."""
    _login(client)
    arbre_fert = {
        "arbre": {
            "noeud": {
                "id": "q_cat_fert",
                "type_noeud": "formulaire",
                "champ": "categorie_fertilisant",
                "branches": [
                    {
                        "valeur": "lisiers",
                        "noeud": {
                            "id": "q_sous_fert",
                            "type_noeud": "formulaire",
                            "champ": "sous_fertilisant",
                            "branches": [],
                        },
                    }
                ],
            }
        }
    }
    tree = DecisionTree.objects.create(
        name="Tree fert create #103",
        contenu=arbre_fert,
        status=DecisionTree.STATUS_DRAFT,
    )
    url = reverse("nitrates_admin_yaml_orm_create", kwargs={"model_key": "fertilisant"})
    resp = client.post(
        url,
        {
            "tree_pk": tree.pk,
            "parent_path": "q_cat_fert/q_sous_fert",
            "target_select": "#sel",
            "identifiant": "fert_test_103",
            "libelle_public": "Fert test 103",
            "type_reglementaire": "type_Ia",
        },
    )
    assert resp.status_code == 200, resp.content
    obj = Fertilisant.objects.get(identifiant="fert_test_103")
    assert obj.categorie == "lisiers"
    assert obj.type_reglementaire == "type_Ia"


def test_post_culture_sans_fk_resolues_refuse(client, tree):
    """Si le parent_path ne donne pas les FK, le POST doit refuser."""
    _login(client)
    url = reverse("nitrates_admin_yaml_orm_create", kwargs={"model_key": "culture"})
    resp = client.post(
        url,
        {
            "tree_pk": tree.pk,
            "parent_path": "",
            "target_select": "#sel",
            "identifiant": "x",
            "libelle_public": "y",
        },
    )
    assert resp.status_code == 400
    assert not Culture.objects.filter(identifiant="x").exists()


def test_post_evenement_phenologique_cree_objet(client, tree):
    _login(client)
    url = reverse(
        "nitrates_admin_yaml_orm_create",
        kwargs={"model_key": "evenement_phenologique"},
    )
    resp = client.post(
        url,
        {
            "tree_pk": tree.pk,
            "parent_path": "",
            "target_select": "#evt",
            "identifiant": "floraison_test_103",
            "libelle_public": "Floraison test",
            "date_calendrier": "15/04",
        },
    )
    assert resp.status_code == 200, resp.content


def test_post_code_prescription_cree_objet(client, tree):
    _login(client)
    url = reverse(
        "nitrates_admin_yaml_orm_create",
        kwargs={"model_key": "code_prescription"},
    )
    resp = client.post(
        url,
        {
            "tree_pk": tree.pk,
            "parent_path": "",
            "target_select": "#cp",
            "identifiant": "pc_test_103",
            "mots_cles": "Test prescription",
            "texte_court": "Texte court test",
            "texte_redaction_initiale": "Texte initiale test",
        },
    )
    assert resp.status_code == 200, resp.content
    assert CodePrescription.objects.filter(identifiant="pc_test_103").exists()
