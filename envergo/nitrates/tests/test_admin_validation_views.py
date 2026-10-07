"""Dashboard de validation des branches (#28, #140) : index, création,
suppression, statut multi-utilisateurs, uploads et auto-save htmx.

La préservation des filtres scope/nature à travers les overrides est
couverte par test_admin_validation_filtres.py.
"""

import io
import json

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from envergo.nitrates.models import (
    BrancheValidation,
    BrancheValidationAction,
    DecisionTree,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def media_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")


@pytest.fixture
def staff(db):
    return get_user_model().objects.create_user(
        email="valideur@test.local", name="Valideur", password="x", is_staff=True
    )


@pytest.fixture
def staff_client(client, staff):
    client.force_login(staff)
    return client


@pytest.fixture
def feuilles(db):
    pan = BrancheValidation.objects.create(
        chemin_yaml="n_zvn/q/r_pan", regle_id="r_pan", ordre=2
    )
    par_couvert = BrancheValidation.objects.create(
        chemin_yaml="n_zvn/q/r_par",
        regle_id="r_par",
        scope=BrancheValidation.SCOPE_PAR_GRAND_EST,
        nature=BrancheValidation.NATURE_COUVERT,
        statut=BrancheValidation.STATUT_VALIDE,
        flag_verif=True,
    )
    zar = BrancheValidation.objects.create(
        chemin_yaml="n_zvn/q/r_zar",
        scope=BrancheValidation.SCOPE_ZAR_GRAND_EST,
        statut=BrancheValidation.STATUT_A_CORRIGER,
        ordre=1,
    )
    return pan, par_couvert, zar


def _png(nom):
    buf = io.BytesIO()
    Image.new("RGB", (2, 2)).save(buf, format="PNG")
    return SimpleUploadedFile(nom, buf.getvalue(), content_type="image/png")


def _url(nom, pk=None):
    kwargs = {"pk": pk} if pk else {}
    # urlconf nitrates posé par le middleware, pas le ROOT_URLCONF des tests.
    return reverse(
        f"nitrates_admin_validation_{nom}",
        kwargs=kwargs,
        urlconf="config.urls_nitrates",
    )


# --- index ------------------------------------------------------------------


def test_index_reserve_au_staff(client, feuilles):
    r = client.get(_url("index"))
    assert r.status_code == 302


def test_index_ordonne_par_arbre_puis_ordre(staff_client, feuilles):
    pan, par_couvert, zar = feuilles

    r = staff_client.get(_url("index"))

    assert r.status_code == 200
    assert list(r.context["branches"]) == [pan, par_couvert, zar]
    assert r.context["stats"] == {
        "total": 3,
        "valide": 1,
        "a_corriger": 1,
        "non_valide": 1,
        "flag_verif": 1,
    }


def test_index_filtres_croises_et_compteurs(staff_client, feuilles):
    _, par_couvert, _ = feuilles

    r = staff_client.get(_url("index"), {"scope": "par_grand_est", "nature": "couvert"})

    assert list(r.context["branches"]) == [par_couvert]
    # Le compteur d'un axe respecte le filtre de l'autre axe.
    assert dict((c, n) for c, _, n in r.context["scopes"])["national"] == 0
    assert dict((c, n) for c, _, n in r.context["natures"])["culture_principale"] == 0


def test_index_ignore_un_filtre_inconnu(staff_client, feuilles):
    r = staff_client.get(_url("index"), {"scope": "pirate", "nature": "pirate"})
    assert r.context["stats"]["total"] == 3


# --- création / suppression -------------------------------------------------


def test_create_get_affiche_le_formulaire(staff_client):
    assert staff_client.get(_url("create")).status_code == 200


def test_create_post_cree_en_fin_de_liste(staff_client, feuilles):
    r = staff_client.post(
        _url("create"), {"chemin_yaml": "manuel/feuille_oubliee", "regle_id": "r_x"}
    )

    b = BrancheValidation.objects.get(chemin_yaml="manuel/feuille_oubliee")
    assert r.status_code == 302 and r.url == _url("detail", b.pk)
    assert b.ordre == 3
    assert b.branche_label == "feuille_oubliee"


def test_create_post_chemin_obligatoire(staff_client):
    r = staff_client.post(_url("create"), {"chemin_yaml": "  "})
    assert r.status_code == 200
    assert not BrancheValidation.objects.exists()


def test_create_post_doublon(staff_client, feuilles):
    r = staff_client.post(_url("create"), {"chemin_yaml": "n_zvn/q/r_pan"})
    assert r.status_code == 200
    assert BrancheValidation.objects.filter(chemin_yaml="n_zvn/q/r_pan").count() == 1


def test_delete(staff_client, feuilles):
    pan, _, _ = feuilles
    r = staff_client.post(_url("delete", pan.pk))
    assert r.url == _url("index")
    assert not BrancheValidation.objects.filter(pk=pan.pk).exists()


# --- détail -----------------------------------------------------------------


def test_detail_pointe_le_viewer_sur_l_arbre_de_la_feuille(staff_client, feuilles):
    _, par_couvert, zar = feuilles
    arbre_par = DecisionTree.objects.create(
        name="PAR GE",
        status=DecisionTree.STATUS_ACTIVE,
        scope=DecisionTree.SCOPE_REGION,
        region_code="44",
        contenu={},
    )

    r = staff_client.get(_url("detail", par_couvert.pk), {"scope": "par_grand_est"})
    assert r.context["arbre_tree_id"] == arbre_par.pk
    assert r.context["scope_actif"] == "par_grand_est"

    # Pas d'arbre ZAR actif : pas de lien viewer plutôt qu'un lien faux.
    r = staff_client.get(_url("detail", zar.pk))
    assert r.context["arbre_tree_id"] is None


def test_detail_scope_inconnu(staff_client):
    b = BrancheValidation.objects.create(chemin_yaml="x", scope="inconnu")
    r = staff_client.get(_url("detail", b.pk))
    assert r.context["arbre_tree_id"] is None


# --- statut -----------------------------------------------------------------


def test_set_statut_empile_les_actions(staff_client, staff, feuilles):
    pan, _, _ = feuilles

    r = staff_client.post(
        _url("set_statut", pan.pk),
        {"statut": "valide", "commentaire": "ok", "scope": "national"},
    )

    assert r.url == _url("index") + "?scope=national"
    pan.refresh_from_db()
    assert pan.statut == "valide"
    action = BrancheValidationAction.objects.get(branche=pan)
    assert (action.user, action.commentaire) == (staff, "ok")


def test_set_statut_invalide_ne_cree_rien(staff_client, feuilles):
    pan, _, _ = feuilles
    r = staff_client.post(_url("set_statut", pan.pk), {"statut": "n_importe_quoi"})
    assert r.url == _url("detail", pan.pk)
    assert not BrancheValidationAction.objects.exists()


# --- uploads et auto-save htmx ----------------------------------------------

UPLOADS = [
    ("upload_miro", "screenshot_miro", "miro"),
    ("upload_yaml_viewer", "screenshot_yaml_viewer", "viewer"),
    ("upload_yaml_form", "screenshot_yaml_form", "form"),
    ("upload_playwright", "screenshot_playwright", "playwright"),
]


@pytest.mark.parametrize("vue,champ,col", UPLOADS)
def test_upload_redirige_sans_htmx(staff_client, feuilles, vue, champ, col):
    pan, _, _ = feuilles

    r = staff_client.post(_url(vue, pan.pk), {champ: _png("c.png")})

    assert r.status_code == 302
    pan.refresh_from_db()
    assert getattr(pan, champ)
    if vue == "upload_playwright":
        assert pan.playwright_run_at is not None


@pytest.mark.parametrize("vue,champ,col", UPLOADS)
def test_upload_htmx_rend_la_colonne(staff_client, feuilles, vue, champ, col):
    pan, _, _ = feuilles

    r = staff_client.post(
        _url(vue, pan.pk), {champ: _png("c.png"), "col": col}, HTTP_HX_REQUEST="true"
    )

    assert r.status_code == 200
    assert json.loads(r["HX-Trigger"])["showToast"]["message"] == "Enregistré ✓"


@pytest.mark.parametrize("vue,champ,col", UPLOADS)
def test_upload_sans_fichier_ne_touche_rien(staff_client, feuilles, vue, champ, col):
    pan, _, _ = feuilles
    staff_client.post(_url(vue, pan.pk))
    pan.refresh_from_db()
    assert not getattr(pan, champ)


def test_edit_meta_champs_textes_et_flag(staff_client, feuilles):
    pan, _, _ = feuilles

    staff_client.post(
        _url("edit_meta", pan.pk),
        {"resultat_miro": "Interdit", "note_verif": "à revoir", "flag_verif": "1"},
    )
    pan.refresh_from_db()
    assert (pan.resultat_miro, pan.note_verif, pan.flag_verif) == (
        "Interdit",
        "à revoir",
        True,
    )

    # Le form de flag sans la case cochée la décoche ; un autre form n'y touche pas.
    staff_client.post(_url("edit_meta", pan.pk), {"note_verif": ""})
    pan.refresh_from_db()
    assert pan.flag_verif is False
    staff_client.post(_url("edit_meta", pan.pk), {"code_pc_miro": "pc1"})
    pan.refresh_from_db()
    assert (pan.code_pc_miro, pan.flag_verif) == ("pc1", False)


def test_edit_meta_htmx_colonne_inconnue_redirige(staff_client, feuilles):
    pan, _, _ = feuilles
    r = staff_client.post(
        _url("edit_meta", pan.pk),
        {"resultat_miro": "x", "col": "inconnue"},
        HTTP_HX_REQUEST="true",
    )
    assert r.status_code == 302


@pytest.mark.parametrize("col", ["yaml", "simulateur"])
def test_edit_meta_htmx_colonnes_texte(staff_client, feuilles, col):
    pan, _, _ = feuilles
    r = staff_client.post(
        _url("edit_meta", pan.pk),
        {"url_simulateur": "/simulateur/?x=1", "col": col},
        HTTP_HX_REQUEST="true",
    )
    assert r.status_code == 200
