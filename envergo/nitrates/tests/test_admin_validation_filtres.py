"""Dashboard de validation (#140) : préservation des filtres scope/nature.

Régression 2026-06-25 : un override (texte Miro, upload image, edit meta…)
dans le détail d'une feuille redirigeait vers le détail SANS repropager
scope/nature -> les hidden du form de validation se vidaient -> au clic
« valider » on retombait sur la liste NON filtrée. Ces tests verrouillent le
fait que les filtres survivent à travers les overrides ET la validation.
"""

import pytest
from django.contrib.auth import get_user_model

from envergo.nitrates.models import BrancheValidation

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_client(db, client):
    """Client pytest-django (host `testserver`, autorisé en settings de test),
    authentifié en staff."""
    User = get_user_model()
    u = User.objects.create_user(
        email="staff_valid@test.local", name="Staff", password="x", is_staff=True
    )
    client.force_login(u)
    return client


@pytest.fixture
def feuille_par(db):
    """Une feuille PAR Grand Est x culture principale."""
    return BrancheValidation.objects.create(
        chemin_yaml="n_zvn/test/par_ge_culture_principale",
        scope=BrancheValidation.SCOPE_PAR_GRAND_EST,
        nature=BrancheValidation.NATURE_CULTURE_PRINCIPALE,
    )


def test_edit_meta_preserve_les_filtres_au_redirect(staff_client, feuille_par):
    """Un override edit_meta redirige vers le détail EN GARDANT scope/nature."""
    r = staff_client.post(
        f"/admin/nitrates/validation/{feuille_par.pk}/edit-meta/",
        {
            "resultat_miro": "x",
            "scope": "par_grand_est",
            "nature": "culture_principale",
        },
    )
    assert r.status_code == 302
    assert "scope=par_grand_est" in r["Location"]
    assert "nature=culture_principale" in r["Location"]


def test_upload_miro_preserve_les_filtres_au_redirect(staff_client, feuille_par):
    r = staff_client.post(
        f"/admin/nitrates/validation/{feuille_par.pk}/upload-miro/",
        {"scope": "par_grand_est", "nature": "culture_principale"},
    )
    assert r.status_code == 302
    assert "scope=par_grand_est" in r["Location"]
    assert "nature=culture_principale" in r["Location"]


def test_detail_reinjecte_les_filtres_dans_le_form_de_validation(
    staff_client, feuille_par
):
    """Le détail rendu avec ?scope&nature met ces valeurs dans les hidden du
    form de validation (sinon la validation suivante les perdrait)."""
    r = staff_client.get(
        f"/admin/nitrates/validation/{feuille_par.pk}/",
        {"scope": "par_grand_est", "nature": "culture_principale"},
    )
    assert r.status_code == 200
    html = r.content.decode()
    assert 'name="scope" value="par_grand_est"' in html
    assert 'name="nature" value="culture_principale"' in html


def test_validation_preserve_les_filtres_au_retour_liste(staff_client, feuille_par):
    """Le clic « valider » redirige vers la liste EN GARDANT le filtre."""
    r = staff_client.post(
        f"/admin/nitrates/validation/{feuille_par.pk}/statut/",
        {
            "statut": "valide",
            "commentaire": "",
            "scope": "par_grand_est",
            "nature": "culture_principale",
        },
    )
    assert r.status_code == 302
    assert "scope=par_grand_est" in r["Location"]
    assert "nature=culture_principale" in r["Location"]
