"""Tests de la matrice des calendriers d'épandage (matrice.py + vue admin).

Le moteur pur (bornes, conditions, linéarisation des régimes) est testé sans
DB ; la construction de matrice s'appuie sur le PAN actif + les référentiels
créés par les migrations data.
"""

import pytest
from django.urls import reverse

from envergo.nitrates.matrice import (
    LIGNES_FERTILISANTS,
    compute_regime_par_jour,
    construire_matrice,
    evaluer_combinaison,
    lignes_cultures,
    parse_borne,
    segments_depuis_regimes,
)
from envergo.nitrates.views_admin_matrice import DATES_DEFAUT_COUVERT
from envergo.nitrates.yaml_tree import load_referentiels, select_active_trees

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_nitrates")]


@pytest.fixture(autouse=True)
def pan_actif(db):
    """Un PAN actif depuis les specs packagées (le test DB réutilisé n'en a
    pas forcément un : d'autres tests purgent les DecisionTree)."""
    from envergo.nitrates.models import DecisionTree
    from envergo.nitrates.yaml_tree.loader import load_arbre

    if not DecisionTree.objects.filter(
        status=DecisionTree.STATUS_ACTIVE, scope=DecisionTree.SCOPE_NATIONAL
    ).exists():
        DecisionTree.objects.create(
            name="PAN test matrice",
            status=DecisionTree.STATUS_ACTIVE,
            scope=DecisionTree.SCOPE_NATIONAL,
            weight=1,
            contenu=load_arbre("arbres_actifs/national"),
        )


# ─── Moteur pur (pas de DB) ────────────────────────────────────────────────


def test_parse_borne_date_fixe():
    b = parse_borne("01/07", {})
    assert (b.jour, b.jour_raw, b.is_event) == (0, 0, False)
    assert parse_borne("30/06", {}).jour == 364


def test_parse_borne_event_et_offset():
    valeurs = {"date_semis_couvert": "15/08"}
    assert parse_borne("date_semis_couvert", valeurs).jour == 45
    b = parse_borne("date_semis_couvert-15jours", valeurs)
    assert b.jour == 30
    # Offset qui franchit le 1er juillet : jour replié, jour_raw brut.
    b = parse_borne("date_semis_couvert-60jours", {"date_semis_couvert": "14/07"})
    assert b.jour_raw < 0
    assert 0 <= b.jour < 365


def test_parse_borne_event_non_saisi():
    assert parse_borne("date_semis_couvert", {}).jour is None


def test_regimes_interdiction_hivernale():
    regimes = compute_regime_par_jour(
        "interdiction", [{"du": "15/12", "au": "15/01"}], {}
    )
    # 15/12 = jour agricole 167, 15/01 = 198.
    assert regimes[167] == "interdiction"
    assert regimes[198] == "interdiction"
    assert regimes[166] == "libre"
    assert regimes[199] == "libre"


def test_regimes_severite_sur_chevauchement():
    regimes = compute_regime_par_jour(
        "mixte",
        [
            {"du": "01/10", "au": "31/01", "regime": "autorisation_sous_condition"},
            {"du": "15/12", "au": "15/01", "regime": "interdiction"},
        ],
        {},
    )
    assert regimes[167] == "interdiction"
    assert regimes[100] == "autorisation_sous_condition"


def test_regimes_masque_sur_intersection_seulement():
    # Masque hors de toute principale : sans effet.
    regimes = compute_regime_par_jour(
        "mixte",
        [
            {"du": "01/10", "au": "30/11", "regime": "autorisation_sous_condition"},
            {"du": "01/03", "au": "30/04", "regime": "interdiction", "masque": True},
        ],
        {},
    )
    assert all(r == "libre" for r in regimes[250:290])
    # Masque sur une principale : il écrase.
    regimes = compute_regime_par_jour(
        "mixte",
        [
            {"du": "01/10", "au": "30/11", "regime": "autorisation_sous_condition"},
            {"du": "01/11", "au": "30/11", "regime": "interdiction", "masque": True},
        ],
        {},
    )
    assert regimes[130] == "interdiction"  # mi-novembre
    assert regimes[100] == "autorisation_sous_condition"  # mi-octobre


def test_regimes_condition_fausse_retire_la_periode():
    periodes = [
        {
            "du": "01/10",
            "au": "30/11",
            "regime": "interdiction",
            "condition": "date_semis_couvert < 01/09",
        }
    ]
    regimes = compute_regime_par_jour(
        "mixte", periodes, {"date_semis_couvert": "15/10"}
    )
    assert all(r == "libre" for r in regimes)
    regimes = compute_regime_par_jour(
        "mixte", periodes, {"date_semis_couvert": "15/08"}
    )
    assert regimes[100] == "interdiction"


def test_regimes_tous_plafonds_repeint_asc_en_libre():
    regimes = compute_regime_par_jour(
        "autorisation_sous_condition",
        [{"du": "01/07", "au": "30/06"}],
        {},
        tous_plafonds=True,
    )
    assert all(r == "libre" for r in regimes)


def test_segments_fusionne_les_couleurs():
    regimes = ["libre"] * 365
    for i in range(167, 199):
        regimes[i] = "interdiction"
    segments = segments_depuis_regimes(regimes)
    assert [s["couleur"] for s in segments] == ["vert", "rouge", "vert"]
    assert abs(sum(s["width_pct"] for s in segments) - 100.0) < 1e-6


# ─── Cascade sans géo (PAN actif des migrations) ───────────────────────────


def test_evaluer_combinaison_hiver_type_0():
    candidats = select_active_trees({"region_code": "32"})
    issue = evaluer_combinaison(
        candidats,
        {
            "en_zone_vulnerable": True,
            "occupation_sol": "culture_principale",
            "sous_culture": "culture_hiver_hors_colza",
            "type_fertilisant": "type_0",
        },
    )
    assert issue["statut"] == "ok"
    assert issue["resultat"].periodes == [{"du": "15/12", "au": "15/01"}]


def test_construire_matrice_axe_fertilisant():
    cellules = construire_matrice(
        region_code="32",
        en_zar=False,
        en_zone_vulnerable=True,
        axe="fertilisant",
        valeur_figee="culture_hiver_hors_colza",
        referentiels=load_referentiels(),
    )
    assert [c.ligne_id for c in cellules] == [f["id"] for f in LIGNES_FERTILISANTS]
    par_id = {c.ligne_id: c for c in cellules}
    type_0 = par_id["type_0"]
    assert type_0.statut == "ok"
    assert any(s["couleur"] == "rouge" for s in type_0.segments)
    # Le type III d'une céréale d'hiver a une fenêtre interdite plus longue.
    assert par_id["type_III"].statut == "ok"


def test_construire_matrice_axe_culture():
    cellules = construire_matrice(
        region_code="32",
        en_zar=False,
        en_zone_vulnerable=True,
        axe="culture",
        valeur_figee="type_II",
        referentiels=load_referentiels(),
    )
    ids = [c.ligne_id for c in cellules]
    assert set(ids) == {ligne["id"] for ligne in lignes_cultures()}
    assert any(c.statut == "ok" for c in cellules)


def test_construire_matrice_hors_zv():
    cellules = construire_matrice(
        region_code="32",
        en_zar=False,
        en_zone_vulnerable=False,
        axe="fertilisant",
        valeur_figee="culture_hiver_hors_colza",
        referentiels=load_referentiels(),
    )
    # Hors ZV : aucune interdiction calendaire.
    for c in cellules:
        assert not any(s["couleur"] == "rouge" for s in c.segments), c.ligne_id


def test_construire_matrice_dates_couvert():
    """Les dates saisies déplacent les segments des lignes calculatrice."""
    kwargs = dict(
        region_code="32",
        en_zar=False,
        en_zone_vulnerable=True,
        axe="fertilisant",
        valeur_figee="cine_avant_3112",
        referentiels=load_referentiels(),
    )
    sans = construire_matrice(**kwargs)
    avec = construire_matrice(
        **kwargs,
        dates={
            "date_semis_couvert": "15/08",
            "date_destruction_couvert": "15/11",
        },
    )
    assert any(c.is_calculatrice for c in avec)
    calc_sans = {c.ligne_id: c.segments for c in sans if c.is_calculatrice}
    calc_avec = {c.ligne_id: c.segments for c in avec if c.is_calculatrice}
    assert calc_sans != calc_avec


# ─── Vue admin ─────────────────────────────────────────────────────────────


def test_vue_matrice_reservee_staff(client):
    url = reverse("nitrates_admin_matrice_index")
    response = client.get(url)
    assert response.status_code == 302
    assert "login" in response["Location"]


def test_vue_matrice_ok_pour_staff(client, django_user_model):
    user = django_user_model.objects.create_user(
        email="staff@example.org", password="x", is_staff=True, name="Staff"
    )
    client.force_login(user)
    url = reverse("nitrates_admin_matrice_index")
    response = client.get(url, {"territoire": "R32", "axe": "fertilisant"})
    assert response.status_code == 200
    assert b"Matrice des calendriers" in response.content


# ─── Dates par défaut selon la branche de couvert ──────────────────────────


def _staff(django_user_model, client):
    user = django_user_model.objects.create_user(
        email="staff-dates@example.org", password="x", is_staff=True, name="Staff"
    )
    client.force_login(user)
    return user


def test_dates_defaut_appliquees_sur_branche_couvert(client, django_user_model):
    """Sans dates dans l'URL, la branche de couvert impose son scénario."""
    _staff(django_user_model, client)
    response = client.get(
        reverse("nitrates_admin_matrice_index"),
        {"territoire": "R44", "axe": "fertilisant", "valeur": "cine_avant_3112"},
    )
    assert response.status_code == 200
    champs = {c["id"]: c["valeur"] for c in response.context["champs_dates"]}
    assert champs["date_destruction_couvert"] == "15/12"
    assert champs["date_semis_couvert"] == "15/08"
    assert response.context["dates_par_defaut"] is True


def test_dates_defaut_distinctes_avant_3112_et_apres_0101(client, django_user_model):
    """Le couvert encore en place après le 01/01 est détruit plus tard."""
    _staff(django_user_model, client)
    url = reverse("nitrates_admin_matrice_index")

    def _destruction(valeur):
        response = client.get(
            url, {"territoire": "R44", "axe": "fertilisant", "valeur": valeur}
        )
        champs = {c["id"]: c["valeur"] for c in response.context["champs_dates"]}
        return champs["date_destruction_couvert"]

    assert _destruction("cine_avant_3112") == "15/12"
    assert _destruction("cine_apres_0101") == "15/02"


def test_saisie_utilisateur_prime_sur_le_defaut(client, django_user_model):
    _staff(django_user_model, client)
    response = client.get(
        reverse("nitrates_admin_matrice_index"),
        {
            "territoire": "R44",
            "axe": "fertilisant",
            "valeur": "cine_avant_3112",
            "date_destruction_couvert": "20/12",
        },
    )
    champs = {c["id"]: c["valeur"] for c in response.context["champs_dates"]}
    assert champs["date_destruction_couvert"] == "20/12"
    assert response.context["dates_par_defaut"] is False


def test_champ_vide_explicitement_reste_vide(client, django_user_model):
    """Vider le champ est un choix : on ne le repeuple pas avec le défaut."""
    _staff(django_user_model, client)
    response = client.get(
        reverse("nitrates_admin_matrice_index"),
        {
            "territoire": "R44",
            "axe": "fertilisant",
            "valeur": "cine_avant_3112",
            "date_destruction_couvert": "",
        },
    )
    champs = {c["id"]: c["valeur"] for c in response.context["champs_dates"]}
    assert champs["date_destruction_couvert"] == ""
    assert response.context["dates_par_defaut"] is False


def test_pas_de_defaut_hors_branche_couvert(client, django_user_model):
    """Axe 'culture' : plusieurs branches coexistent, aucun défaut unique."""
    _staff(django_user_model, client)
    response = client.get(
        reverse("nitrates_admin_matrice_index"),
        {"territoire": "R44", "axe": "culture", "valeur": "type_Ia"},
    )
    champs = {c["id"]: c["valeur"] for c in response.context["champs_dates"]}
    assert champs["date_destruction_couvert"] == ""
    assert response.context["dates_par_defaut"] is False


@pytest.mark.parametrize("branche", sorted(DATES_DEFAUT_COUVERT))
def test_defauts_rendent_les_calculatrices_non_plates(branche):
    """Garde-fou anti-régression : une cellule calculatrice ne doit jamais
    s'afficher 100% verte avec les dates par défaut — ça se lirait « autorisé
    toute l'année » alors que ça veut dire « bornes irrésolues »."""
    cellules = construire_matrice(
        region_code="44",
        en_zar=False,
        en_zone_vulnerable=True,
        axe="fertilisant",
        valeur_figee=branche,
        referentiels=load_referentiels(),
        dates=dict(DATES_DEFAUT_COUVERT[branche]),
    )
    # Toutes les branches n'ont pas de feuille calculatrice selon l'arbre
    # actif : on n'en exige pas, on vérifie celles qui existent.
    calculatrices = [c for c in cellules if c.is_calculatrice and c.statut == "ok"]
    for cellule in calculatrices:
        couleurs = {s["couleur"] for s in cellule.segments}
        assert couleurs != {"vert"}, f"{branche}/{cellule.ligne_id} est plate"
