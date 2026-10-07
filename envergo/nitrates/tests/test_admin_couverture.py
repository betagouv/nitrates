"""Tests de couverture de l'admin Django nitrates (envergo/nitrates/admin.py).

Vise les comportements observables non couverts ailleurs : pages
changelist/change pour un superuser, affichages (yaml_preview, edit_link,
actions_links, status_badge, a_du_contenu_riche, apercu_rendu, apercu,
contexte_lisible), actions bulk, et validations de formulaire.
"""

import pytest
from django.contrib.admin.sites import AdminSite
from django.test import Client
from django.urls import reverse

from envergo.nitrates.admin import (
    CodePrescriptionAdmin,
    CodePrescriptionForm,
    ContenuRichDSFRAdmin,
    CouleurZoneAdmin,
    DecisionTreeAdmin,
    RetourUtilisateurAdmin,
    _clean_blocs_json,
)
from envergo.nitrates.models import DecisionTree
from envergo.nitrates.models_carto import CouleurZone
from envergo.nitrates.models_contenu_rich import ContenuRichDSFR
from envergo.nitrates.models_ouverture import DepartementOuverture
from envergo.nitrates.models_referentiels import CodePrescription, NoteReglementaire
from envergo.nitrates.models_retour import RetourUtilisateur
from envergo.users.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def superuser_client(db):
    u = User.objects.create(
        email="super-admin@test.local", is_staff=True, is_superuser=True, is_active=True
    )
    c = Client()
    c.force_login(u)
    return c, u


# ---------------------------------------------------------------------------
# _clean_blocs_json
# ---------------------------------------------------------------------------


def test_clean_blocs_json_dict_passthrough():
    assert _clean_blocs_json({"a": 1}) == {"a": 1}


def test_clean_blocs_json_vide_renvoie_enveloppe():
    assert _clean_blocs_json("") == {"schema": 1, "blocs": []}
    assert _clean_blocs_json(None) == {"schema": 1, "blocs": []}


def test_clean_blocs_json_string_valide():
    assert _clean_blocs_json('{"schema": 1, "blocs": []}') == {
        "schema": 1,
        "blocs": [],
    }


def test_clean_blocs_json_illisible_leve_validation_error():
    from django import forms

    with pytest.raises(forms.ValidationError):
        _clean_blocs_json("{pas du json")


# ---------------------------------------------------------------------------
# DecisionTreeAdmin : pages admin + permissions observables
# ---------------------------------------------------------------------------


def _make_tree(status, created_by=None, name="t", scope="national"):
    if status == DecisionTree.STATUS_ACTIVE:
        DecisionTree.objects.filter(status=DecisionTree.STATUS_ACTIVE).delete()
    return DecisionTree.objects.create(
        name=name,
        status=status,
        scope=scope,
        contenu={},
        contenu_yaml_brut="schema: 1\narbre: {}",
        created_by=created_by,
    )


def test_changelist_decisiontree_superuser_200(superuser_client):
    c, u = superuser_client
    _make_tree(DecisionTree.STATUS_DRAFT, u, name="d1")
    _make_tree(DecisionTree.STATUS_ACTIVE, u, name="a1")
    _make_tree(DecisionTree.STATUS_ARCHIVE, u, name="arch1")
    url = reverse("admin:nitrates_decisiontree_changelist")
    resp = c.get(url)
    assert resp.status_code == 200
    # Le tri par defaut (actif puis draft puis archive) doit afficher les 3.
    content = resp.content.decode()
    assert "d1" in content and "a1" in content and "arch1" in content


def test_change_decisiontree_affiche_yaml_preview_et_edit_link(superuser_client):
    c, u = superuser_client
    tree = _make_tree(DecisionTree.STATUS_DRAFT, u, name="d2")
    url = reverse("admin:nitrates_decisiontree_change", args=[tree.pk])
    resp = c.get(url)
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "yaml-raw" in content  # yaml_preview rendu via pygments
    assert "Éditer ce brouillon" in content  # edit_link sur un draft


@pytest.mark.urls("config.urls_nitrates")
def test_edit_link_sur_arbre_actif(superuser_client):
    c, u = superuser_client
    tree = _make_tree(DecisionTree.STATUS_ACTIVE, u, name="actif1")
    admin_instance = DecisionTreeAdmin(DecisionTree, AdminSite())
    html = admin_instance.edit_link(tree)
    assert "Éditer cet arbre" in html


@pytest.mark.urls("config.urls_nitrates")
def test_edit_link_sur_archive_propose_clonage(superuser_client):
    c, u = superuser_client
    tree = _make_tree(DecisionTree.STATUS_ARCHIVE, u, name="arch2")
    admin_instance = DecisionTreeAdmin(DecisionTree, AdminSite())
    html = admin_instance.edit_link(tree)
    assert "Cloner en draft" in html


def test_edit_link_sans_objet():
    admin_instance = DecisionTreeAdmin(DecisionTree, AdminSite())
    assert admin_instance.edit_link(None) == "—"


def test_yaml_preview_vide_sans_crash():
    admin_instance = DecisionTreeAdmin(DecisionTree, AdminSite())
    tree = DecisionTree(name="x", status="draft", contenu={}, contenu_yaml_brut="")
    assert admin_instance.yaml_preview(tree) == "(vide)"


def test_status_badge_pour_chaque_statut():
    admin_instance = DecisionTreeAdmin(DecisionTree, AdminSite())
    for status in (
        DecisionTree.STATUS_DRAFT,
        DecisionTree.STATUS_ACTIVE,
        DecisionTree.STATUS_ARCHIVE,
    ):
        tree = DecisionTree(name="x", status=status, contenu={})
        html = admin_instance.status_badge(tree)
        assert tree.get_status_display() in html


def test_region_col_et_weight_col():
    admin_instance = DecisionTreeAdmin(DecisionTree, AdminSite())
    tree = DecisionTree(name="x", status="draft", region_code="44", weight=7)
    assert admin_instance.region_col(tree) == "44"
    assert admin_instance.weight_col(tree) == 7
    tree_sans_region = DecisionTree(name="x", status="draft", region_code="")
    assert admin_instance.region_col(tree_sans_region) == "—"


@pytest.mark.urls("config.urls_nitrates")
def test_actions_links_pour_chaque_statut(superuser_client):
    c, u = superuser_client
    admin_instance = DecisionTreeAdmin(DecisionTree, AdminSite())
    draft = _make_tree(DecisionTree.STATUS_DRAFT, u, name="dd")
    html_draft = admin_instance.actions_links(draft)
    assert "Éditer" in html_draft and "Cloner" in html_draft

    actif = _make_tree(DecisionTree.STATUS_ACTIVE, u, name="aa")
    html_actif = admin_instance.actions_links(actif)
    assert "Éditer" in html_actif and "Cloner" in html_actif

    archive = _make_tree(DecisionTree.STATUS_ARCHIVE, u, name="rr")
    html_archive = admin_instance.actions_links(archive)
    assert "Éditer" not in html_archive
    assert "Cloner" in html_archive


def test_clone_to_draft_action_cree_un_draft(superuser_client):
    """L'action admin clone_to_draft modifie bien la base : un nouveau
    DecisionTree draft apparait, lie a la source."""
    c, u = superuser_client
    source = _make_tree(DecisionTree.STATUS_ACTIVE, u, name="source-clone")
    url = reverse("admin:nitrates_decisiontree_changelist")
    n_avant = DecisionTree.objects.count()
    resp = c.post(
        url,
        {
            "action": "clone_to_draft",
            "_selected_action": [str(source.pk)],
        },
        follow=False,
    )
    assert resp.status_code == 302
    assert DecisionTree.objects.count() == n_avant + 1
    nouveau_draft = DecisionTree.objects.exclude(pk=source.pk).get(
        status=DecisionTree.STATUS_DRAFT, parent=source
    )
    assert nouveau_draft.created_by_id == u.pk


def test_clone_to_draft_refuse_plusieurs_lignes(superuser_client):
    """Selectionner 2 lignes a cloner ne cree rien et affiche une erreur."""
    c, u = superuser_client
    t1 = _make_tree(DecisionTree.STATUS_DRAFT, u, name="multi1")
    t2 = _make_tree(DecisionTree.STATUS_DRAFT, u, name="multi2")
    url = reverse("admin:nitrates_decisiontree_changelist")
    n_avant = DecisionTree.objects.count()
    resp = c.post(
        url,
        {
            "action": "clone_to_draft",
            "_selected_action": [str(t1.pk), str(t2.pk)],
        },
        follow=True,
    )
    assert resp.status_code == 200
    assert DecisionTree.objects.count() == n_avant
    assert "Sélectionnez exactement une ligne" in resp.content.decode()


# ---------------------------------------------------------------------------
# CodePrescriptionForm : validation des composants de fusion (#147)
# ---------------------------------------------------------------------------


@pytest.fixture
def note_reglementaire(db):
    return NoteReglementaire.objects.create(
        identifiant="note_cov",
        libelle_court="Note couverture",
        condition_declenchement="toujours",
    )


def _pc(identifiant, **kwargs):
    defaults = {
        "texte_court": "texte",
        "texte_redaction_initiale": "",
    }
    defaults.update(kwargs)
    return CodePrescription.objects.create(identifiant=identifiant, **defaults)


def test_code_prescription_form_clean_blocs_invalide():
    pc = _pc("pc_cov1")
    form = CodePrescriptionForm(
        data={
            "identifiant": "pc_cov1",
            "texte_court": "texte",
            "blocs": "{json cassé",
            "ordre_affichage": 0,
        },
        instance=pc,
    )
    assert not form.is_valid()
    assert "blocs" in form.errors


def test_code_prescription_form_fusion_ne_peut_pas_se_contenir(db):
    pc = _pc("pc_cov2")
    form = CodePrescriptionForm(
        data={
            "identifiant": "pc_cov2",
            "texte_court": "texte",
            "blocs": "{}",
            "ordre_affichage": 0,
            "composants_fusion": [pc.pk],
        },
        instance=pc,
    )
    assert not form.is_valid()
    assert any("elle-même" in e for e in form.errors.get("__all__", []))


def test_code_prescription_form_composant_declinaison_rejete(db):
    base = _pc("pc_cov_base")
    declinaison = _pc("pc_cov_decl", variante_de=base)
    fusion = _pc("pc_cov_fusion")
    form = CodePrescriptionForm(
        data={
            "identifiant": "pc_cov_fusion",
            "texte_court": "texte",
            "blocs": "{}",
            "ordre_affichage": 0,
            "composants_fusion": [declinaison.pk],
        },
        instance=fusion,
    )
    assert not form.is_valid()
    assert any("déclinaisons" in e for e in form.errors.get("__all__", []))


def test_code_prescription_form_pas_de_fusion_de_fusions(db):
    composant_a = _pc("pc_cov_a")
    _pc("pc_cov_b")
    sous_fusion = _pc("pc_cov_sous_fusion")
    sous_fusion.composants_fusion.add(composant_a)
    fusion = _pc("pc_cov_fusion2")
    form = CodePrescriptionForm(
        data={
            "identifiant": "pc_cov_fusion2",
            "texte_court": "texte",
            "blocs": "{}",
            "ordre_affichage": 0,
            "composants_fusion": [sous_fusion.pk],
        },
        instance=fusion,
    )
    assert not form.is_valid()
    assert any("fusion de fusions" in e for e in form.errors.get("__all__", []))


def test_code_prescription_form_declinaison_avec_composants_rejetee(db):
    base = _pc("pc_cov_base2")
    composant = _pc("pc_cov_c")
    declinaison = _pc("pc_cov_decl2", variante_de=base)
    form = CodePrescriptionForm(
        data={
            "identifiant": "pc_cov_decl2",
            "texte_court": "texte",
            "blocs": "{}",
            "ordre_affichage": 0,
            "scope": "region",
            "region_code": "44",
            "variante_de": base.pk,
            "composants_fusion": [composant.pk],
        },
        instance=declinaison,
    )
    assert not form.is_valid()
    assert any("déclinaison géographique" in e for e in form.errors.get("__all__", []))


def test_code_prescription_form_fusion_valide(db):
    composant = _pc("pc_cov_valide")
    fusion = _pc("pc_cov_fusion_ok")
    form = CodePrescriptionForm(
        data={
            "identifiant": "pc_cov_fusion_ok",
            "texte_court": "texte",
            "blocs": "{}",
            "ordre_affichage": 0,
            "scope": "national",
            "composants_fusion": [composant.pk],
        },
        instance=fusion,
    )
    assert form.is_valid(), form.errors


# ---------------------------------------------------------------------------
# Affichages (display methods) : CodePrescription, ContenuRichDSFR, CouleurZone
# ---------------------------------------------------------------------------


def test_a_du_contenu_riche_vrai_et_faux():
    admin_instance = CodePrescriptionAdmin(CodePrescription, AdminSite())
    avec = CodePrescription(blocs={"blocs": [{"type": "texte"}]})
    sans = CodePrescription(blocs={"blocs": []})
    legacy_vide = CodePrescription(blocs={})
    assert admin_instance.a_du_contenu_riche(avec) is True
    assert admin_instance.a_du_contenu_riche(sans) is False
    assert admin_instance.a_du_contenu_riche(legacy_vide) is False


def test_apercu_rendu_code_prescription_sans_pk():
    admin_instance = CodePrescriptionAdmin(CodePrescription, AdminSite())
    assert "enregistrer d'abord" in admin_instance.apercu_rendu(CodePrescription())


@pytest.mark.urls("config.urls_nitrates")
def test_apercu_rendu_code_prescription_avec_pk(db):
    admin_instance = CodePrescriptionAdmin(CodePrescription, AdminSite())
    pc = _pc("pc_cov_apercu")
    html = admin_instance.apercu_rendu(pc)
    assert "Prévisualiser le rendu" in html
    assert f"id={pc.pk}" in html


@pytest.mark.urls("config.urls_nitrates")
def test_apercu_rendu_contenu_rich_dsfr(db):
    admin_instance = ContenuRichDSFRAdmin(ContenuRichDSFR, AdminSite())
    assert "enregistrer d'abord" in admin_instance.apercu_rendu(ContenuRichDSFR())
    contenu = ContenuRichDSFR.objects.create(cle="cov.test", libelle_admin="Test")
    html = admin_instance.apercu_rendu(contenu)
    assert "Prévisualiser le rendu" in html


def test_apercu_couleur_zone():
    admin_instance = CouleurZoneAdmin(CouleurZone, AdminSite())
    zone = CouleurZone(cle="FRA", couleur="#00b0ff")
    html = admin_instance.apercu(zone)
    assert "#00b0ff" in html


# ---------------------------------------------------------------------------
# DepartementOuverture : actions bulk ouvrir/fermer
# ---------------------------------------------------------------------------


def test_ouvrir_et_fermer_selection_departements(superuser_client):
    c, u = superuser_client
    d1 = DepartementOuverture.objects.create(
        code="Z91", nom="Dept test 1", est_ouvert=False
    )
    d2 = DepartementOuverture.objects.create(
        code="Z92", nom="Dept test 2", est_ouvert=False
    )
    url = reverse("admin:nitrates_departementouverture_changelist")
    resp = c.post(
        url,
        {
            "action": "ouvrir_selection",
            "_selected_action": [str(d1.pk), str(d2.pk)],
        },
        follow=True,
    )
    assert resp.status_code == 200
    d1.refresh_from_db()
    d2.refresh_from_db()
    assert d1.est_ouvert is True and d2.est_ouvert is True

    resp = c.post(
        url,
        {
            "action": "fermer_selection",
            "_selected_action": [str(d1.pk)],
        },
        follow=True,
    )
    assert resp.status_code == 200
    d1.refresh_from_db()
    assert d1.est_ouvert is False
    d2.refresh_from_db()
    assert d2.est_ouvert is True  # non selectionne, inchange


# ---------------------------------------------------------------------------
# RetourUtilisateur : lecture seule + contexte_lisible
# ---------------------------------------------------------------------------


def test_retour_utilisateur_permissions_lecture_seule():
    admin_instance = RetourUtilisateurAdmin(RetourUtilisateur, AdminSite())
    assert admin_instance.has_add_permission(None) is False
    assert admin_instance.has_change_permission(None) is True
    assert admin_instance.has_delete_permission(None) is True


def test_a_email_et_apercu_commentaire():
    admin_instance = RetourUtilisateurAdmin(RetourUtilisateur, AdminSite())
    retour = RetourUtilisateur(email="x@y.fr", commentaire="a" * 80)
    assert admin_instance.a_email(retour) is True
    apercu = admin_instance.apercu_commentaire(retour)
    assert apercu.endswith("…")
    assert len(apercu) == 61  # 60 caracteres + l'ellipse

    retour_court = RetourUtilisateur(email="", commentaire="court")
    assert admin_instance.a_email(retour_court) is False
    assert admin_instance.apercu_commentaire(retour_court) == "court"


def test_contexte_lisible_vide():
    admin_instance = RetourUtilisateurAdmin(RetourUtilisateur, AdminSite())
    assert admin_instance.contexte_lisible(RetourUtilisateur(contexte={})) == "—"
    assert admin_instance.contexte_lisible(RetourUtilisateur(contexte=None)) == "—"


def test_contexte_lisible_rend_page_logs_et_reseau(db):
    admin_instance = RetourUtilisateurAdmin(RetourUtilisateur, AdminSite())
    retour = RetourUtilisateur.objects.create(
        type=RetourUtilisateur.Type.BUG,
        commentaire="bug",
        contexte={
            "url": "https://exemple.fr/simulateur",
            "titre_page": "Simulateur",
            "user_agent": "Mozilla/5.0",
            "viewport": "1920x1080",
            "referrer": "https://exemple.fr",
            "horodatage": "2026-10-07T10:00:00Z",
            "console": [{"level": "error", "message": "boom"}],
            "network": [{"method": "GET", "url": "/x", "status": 500}],
        },
    )
    html = admin_instance.contexte_lisible(retour)
    assert "Simulateur" in html
    assert "Console (1 entrées)" in html
    assert "boom" in html
    assert "Réseau (1 requêtes)" in html
    assert "GET /x → 500" in html


def test_changelist_retour_utilisateur_superuser_200(superuser_client):
    c, u = superuser_client
    RetourUtilisateur.objects.create(
        type=RetourUtilisateur.Type.FEEDBACK, note=4, commentaire="utile"
    )
    url = reverse("admin:nitrates_retourutilisateur_changelist")
    resp = c.get(url)
    assert resp.status_code == 200


def test_change_retour_utilisateur_readonly_superuser_200(superuser_client):
    c, u = superuser_client
    retour = RetourUtilisateur.objects.create(
        type=RetourUtilisateur.Type.FEEDBACK, note=2, commentaire="bof"
    )
    url = reverse("admin:nitrates_retourutilisateur_change", args=[retour.pk])
    resp = c.get(url)
    assert resp.status_code == 200
    # Aucun champ editable (readonly_fields couvre tout) : pas de bouton
    # "Enregistrer et continuer" standard, mais la page s'affiche bien.
    assert "bof" in resp.content.decode()
