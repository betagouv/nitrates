"""Tests du moteur APLSH (parsing + calcul, sans DB).

Les valeurs attendues viennent des exemples chiffrés des arrêtés GREN
(voir ~/Data/betagouv/specs/APLSH/APLSH_extraction_et_analyse.md).
"""

from datetime import date

import pytest
from django.urls import reverse

from envergo.nitrates.aplsh import (
    ErreurTableauAPLSH,
    calculer,
    parser_tableau_generique,
    parser_tableau_produits,
    resoudre_p_generique,
    saison_apport,
)

FERTILISANTS = {"dejection_sans_litiere", "fumier_volaille"}


def test_parser_produits_nominal():
    texte = """
    # commentaire
    fertilisant | variante | unite | n_total | p_ete | p_automne
    dejection_sans_litiere | Lisier de bovins | m3 | 2,9 | 65% | 0.60
    fumier_volaille | | | | 45% | 30%
    """
    lignes = parser_tableau_produits(texte, FERTILISANTS)
    assert lignes[0] == {
        "fertilisant": "dejection_sans_litiere",
        "variante": "Lisier de bovins",
        "unite": "m3",
        "n_total": 2.9,
        "p_ete": 0.65,
        "p_automne": 0.60,
    }
    assert lignes[1]["n_total"] is None  # teneur absente (cas HdF)


@pytest.mark.parametrize(
    "ligne, message",
    [
        ("inconnu | | t | 1 | 10% | 10%", "fertilisant inconnu"),
        ("fumier_volaille | | t | 1 | 150% | 10%", "hors de"),
        ("fumier_volaille | | t | 1 | 10%", "au lieu de"),
        ("fumier_volaille | | t | -2 | 10% | 10%", "n_total"),
        ("fumier_volaille | | kg | 2 | 10% | 10%", "invalide"),
        (
            "fumier_volaille | a | t | 1 | 10% | 10%\n"
            "fumier_volaille | a | t | 2 | 20% | 20%",
            "doublon",
        ),
    ],
)
def test_parser_produits_erreurs(ligne, message):
    with pytest.raises(ErreurTableauAPLSH, match=message):
        parser_tableau_produits(ligne, FERTILISANTS)


def test_parser_produits_vide():
    with pytest.raises(ErreurTableauAPLSH, match="vide"):
        parser_tableau_produits("# rien\n", FERTILISANTS)


GRILLE = """
8 | 20% | 50% | 45%
8 | 40% | 60% | 60%
8 | | 70% | 70%
20 | 20% | 20% | 15%
| | 30% | 30%
"""


def test_grille_generique_resolution():
    grille = parser_tableau_generique(GRILLE)
    # Exemple de l'arrêté GE : digestat C/N 9, Nmin/Ntot 56 % → hors
    # tranches <=8, tombe en 10-20 dans l'arrêté complet ; ici grille
    # tronquée : C/N 7, ratio 30 % → 60 %.
    assert resoudre_p_generique(grille, 7, 0.30)["p_ete"] == 0.60
    assert resoudre_p_generique(grille, 7, 0.90)["p_ete"] == 0.70
    assert resoudre_p_generique(grille, 15, 0.10)["p_automne"] == 0.15
    assert resoudre_p_generique(grille, 99, 0.99)["p_ete"] == 0.30


def test_saison_apport():
    assert saison_apport(date(2026, 8, 15), "15/09") == "ete"
    assert saison_apport(date(2026, 9, 15), "15/09") == "ete"
    assert saison_apport(date(2026, 9, 16), "15/09") == "automne"
    assert saison_apport(date(2026, 11, 2), "15/09") == "automne"
    # Janvier (jusqu'au 15/01) = fin de la fenêtre APLSH → automne
    assert saison_apport(date(2027, 1, 10), "15/09") == "automne"
    # Borne HdF
    assert saison_apport(date(2026, 9, 1), "31/08") == "automne"


def test_calcul_exemple_arrete_ge_lisier():
    # Arrêté GE : 20 m³ lisier de bovins (2,9 kg N/m³, p été 65 %) sur
    # prairie → ~38 kg APLSH < 70, conforme.
    r = calculer(plafond=70, n_total=2.9, p=0.65, saison="ete", dose=20)
    assert r.aplsh == pytest.approx(37.7, abs=0.05)
    assert r.conforme is True
    assert r.dose_max == pytest.approx(37.1, abs=0.05)


def test_calcul_exemple_arrete_hdf_dose_max():
    # Annexe 14 HdF : lisier de bovins non dilué 4,5 kg N/m³, p été 0,55,
    # seuil 70 → 28 m³/ha.
    r = calculer(plafond=70, n_total=4.5, p=0.55, saison="ete")
    assert r.dose_max == pytest.approx(28.3, abs=0.05)
    assert r.aplsh is None


def test_calcul_depassement():
    r = calculer(plafond=70, n_total=4.5, p=0.55, saison="ete", dose=40)
    assert r.conforme is False


def test_ressaisir_la_dose_max_affichee_reste_conforme():
    # Bug d'arrondi : la dose max affichée (arrondie) reportée en dose
    # envisagée doit rester conforme (tolérance 0,5 %).
    r = calculer(plafond=70, n_total=15.0, p=1.0, saison="ete")
    affichee = r.dose_max_affichee
    assert affichee <= r.dose_max
    r2 = calculer(
        plafond=70, n_total=15.0, p=1.0, saison="ete", dose=round(r.dose_max, 1)
    )
    assert r2.conforme is True


def test_plafond_170_effluents_elevage():
    # Fumier de caprins GE : 6,1 kg N/t, p été 0,20. Le seul plafond APLSH
    # donnerait 57,4 t/ha — lunaire : 350 kg N total/ha. Le garde-fou des
    # 170 kg N d'effluents d'élevage/ha/an doit borner à 27,9 t/ha.
    r = calculer(70, 6.1, 0.20, "ete", plafond_azote_total=170)
    assert r.dose_max_aplsh == pytest.approx(57.4, abs=0.05)
    assert r.dose_max == pytest.approx(27.9, abs=0.05)
    assert r.limite == "azote_total"
    # Lisier de bovins : l'APLSH reste la contrainte active (37,1 < 58,6).
    r2 = calculer(70, 2.9, 0.65, "ete", plafond_azote_total=170)
    assert r2.limite == "aplsh"
    assert r2.dose_max == pytest.approx(37.1, abs=0.05)
    # Sans borne (minéral, boues…) : comportement inchangé.
    r3 = calculer(70, 6.1, 0.20, "ete")
    assert r3.dose_max == pytest.approx(57.4, abs=0.05)


# ─── Flag NITRATES_POC_APLSH (pages activées sur dev seulement) ─────────────


@pytest.fixture
def staff_client(client, django_user_model):
    user = django_user_model.objects.create_superuser(
        email="staff-aplsh@example.org", password="x", name="Staff"
    )
    client.force_login(user)
    return client


@pytest.mark.django_db
@pytest.mark.urls("config.urls_nitrates")
@pytest.mark.parametrize(
    "url_name", ["nitrates_admin_aplsh_index", "nitrates_admin_meteo_index"]
)
def test_pages_poc_404_hors_flag(staff_client, settings, url_name):
    settings.NITRATES_POC_APLSH = False
    assert staff_client.get(reverse(url_name)).status_code == 404


@pytest.mark.django_db
@pytest.mark.urls("config.urls_nitrates")
def test_calculette_ok_avec_flag(staff_client, settings):
    settings.NITRATES_POC_APLSH = True
    response = staff_client.get(reverse("nitrates_admin_aplsh_index"))
    assert response.status_code == 200


@pytest.mark.django_db
@pytest.mark.urls("config.urls_nitrates")
@pytest.mark.parametrize("actif", [True, False])
def test_liens_accueil_admin_selon_flag(staff_client, settings, actif):
    settings.NITRATES_POC_APLSH = actif
    url = reverse("admin:app_list", kwargs={"app_label": "nitrates"})
    content = staff_client.get(url).content.decode()
    assert (reverse("nitrates_admin_aplsh_index") in content) is actif
    assert (reverse("nitrates_admin_meteo_index") in content) is actif
    assert ("referentielaplsh" in content) is actif
