"""Tests de la matrice des calendriers d'épandage (matrice.py + vue admin).

Le moteur pur (bornes, conditions, linéarisation des régimes) est testé sans
DB ; la construction de matrice s'appuie sur le PAN actif + les référentiels
créés par les migrations data.
"""

import pytest
from django.urls import reverse

from envergo.nitrates.matrice import (
    LIGNES_FERTILISANTS,
    cle_affichage,
    compute_regime_par_jour,
    construire_matrice,
    evaluer_combinaison,
    lignes_cultures,
    parse_borne,
    questions_rencontrees,
    segments_depuis_regimes,
    zonages_rencontres,
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


# ─── Questions complémentaires rejouables ──────────────────────────────────


def test_questions_rencontrees_dedoublonne_par_champ():
    cellules = construire_matrice(
        region_code="44",
        en_zar=False,
        en_zone_vulnerable=True,
        axe="fertilisant",
        valeur_figee="cine_avant_3112",
        referentiels=load_referentiels(),
        dates=dict(DATES_DEFAUT_COUVERT["cine_avant_3112"]),
    )
    questions = questions_rencontrees(cellules)
    textes = [q["texte"] for q in questions]
    assert len(textes) == len(
        set(textes)
    ), "une question ne doit s'afficher qu'une fois"
    plan = next(q for q in questions if "plan d'épandage ICPE" in q["texte"])
    assert plan["par_defaut"] is True
    assert plan["lignes"], "la question doit porter sur au moins une ligne"
    assert plan["libelle_retenu"] == "Non concerné"


def test_reponse_explicite_change_la_feuille_atteinte():
    """Le cœur du besoin : répondre à une QC doit rejouer la cascade."""
    commun = dict(
        region_code="44",
        en_zar=False,
        en_zone_vulnerable=True,
        axe="fertilisant",
        valeur_figee="cine_avant_3112",
        referentiels=load_referentiels(),
        dates=dict(DATES_DEFAUT_COUVERT["cine_avant_3112"]),
    )
    defaut = construire_matrice(**commun)
    force = construire_matrice(**commun, reponses={"plan_epandage": "icpe_a"})

    def _ia(cellules):
        return next(c for c in cellules if c.ligne_id == "type_Ia")

    assert _ia(defaut).chemin[-1] != _ia(force).chemin[-1]
    # La réponse explicite n'est plus une hypothèse.
    assert len(_ia(force).hypotheses) < len(_ia(defaut).hypotheses)


def test_vue_expose_les_questions_et_rejoue_la_reponse(client, django_user_model):
    user = django_user_model.objects.create_user(
        email="staff-qc@example.org", password="x", is_staff=True, name="Staff"
    )
    client.force_login(user)
    url = reverse("nitrates_admin_matrice_index")
    params = {"territoire": "R44", "axe": "fertilisant", "valeur": "cine_avant_3112"}

    defaut = client.get(url, params)
    assert defaut.status_code == 200
    champs = {q["champ"] for q in defaut.context["questions"]}
    assert "plan_epandage" in champs

    # Libellé lu dans l'arbre actif (il varie d'une version à l'autre) : on
    # prend la première réponse qui n'est pas celle retenue par défaut.
    plan_defaut = next(
        q for q in defaut.context["questions"] if "plan d'épandage ICPE" in q["texte"]
    )
    libelle = next(
        lib
        for lib in plan_defaut["valeurs_par_libelle"]
        if lib != plan_defaut["libelle_retenu"]
    )
    force = client.get(url, {**params, "qc_plan_epandage": libelle})
    assert force.status_code == 200
    plan = next(
        q for q in force.context["questions"] if "plan d'épandage ICPE" in q["texte"]
    )
    assert plan["libelle_retenu"] == libelle
    assert plan["par_defaut"] is False


def test_question_reste_affichee_meme_si_la_reponse_ferme_sa_branche(
    client, django_user_model
):
    """Sans ça, l'utilisateur ne pourrait pas revenir sur son choix."""
    user = django_user_model.objects.create_user(
        email="staff-qc2@example.org", password="x", is_staff=True, name="Staff"
    )
    client.force_login(user)
    response = client.get(
        reverse("nitrates_admin_matrice_index"),
        {
            "territoire": "R44",
            "axe": "fertilisant",
            "valeur": "cine_avant_3112",
            "qc_plan_epandage": "Oui, plan d'épandage ICPE soumis à autorisation",
        },
    )
    textes = [q["texte"] for q in response.context["questions"]]
    assert any("plan d'épandage ICPE" in t for t in textes)


def test_reponse_inconnue_est_ignoree(client, django_user_model):
    """Une valeur forgée dans l'URL ne doit pas entrer dans le contexte."""
    user = django_user_model.objects.create_user(
        email="staff-qc3@example.org", password="x", is_staff=True, name="Staff"
    )
    client.force_login(user)
    response = client.get(
        reverse("nitrates_admin_matrice_index"),
        {
            "territoire": "R44",
            "axe": "fertilisant",
            "valeur": "cine_avant_3112",
            "qc_plan_epandage": "libelle_qui_nexiste_pas",
        },
    )
    assert response.status_code == 200
    plan = next(
        q for q in response.context["questions"] if "plan d'épandage ICPE" in q["texte"]
    )
    assert plan["par_defaut"] is True


def test_questions_identiques_sous_des_champs_differents_ne_sont_affichees_quune_fois():
    """Non-régression : 3 champs (`fertilisant_iaa`, `icpe_ed`,
    `pas_un_digestats`) posent le MÊME libellé, et « Non concerné » se code
    différemment selon la branche (`non_concerne`/`Non`/`autre`/`icpe_autre`).
    Grouper sur les identifiants techniques affichait le même contrôle 4 fois.
    Les arbres sont écrits pour des humains : on regroupe sur ce qui est lu.
    """
    cellules = construire_matrice(
        region_code="44",
        en_zar=False,
        en_zone_vulnerable=True,
        axe="fertilisant",
        valeur_figee="cine_avant_3112",
        referentiels=load_referentiels(),
        dates=dict(DATES_DEFAUT_COUVERT["cine_avant_3112"]),
    )
    questions = questions_rencontrees(cellules)
    textes = [q["texte"] for q in questions]
    assert len(textes) == len(set(textes))

    # Le nombre exact de champs dépend de l'arbre actif : on vérifie
    # l'invariant (plusieurs champs regroupés sous UN contrôle), pas la donnée.
    iaa = next(q for q in questions if "issu de traitement" in q["texte"])
    assert len(iaa["champs"]) > 1, "les champs jumeaux doivent être regroupés"

    plan = next(q for q in questions if "plan d'épandage ICPE" in q["texte"])
    # Un seul contrôle, et « Non concerné » sait se traduire pour chaque champ.
    assert len(plan["valeurs_par_libelle"]["Non concerné"]) >= 1


def test_reponse_traduite_vers_le_codage_de_chaque_champ():
    """Répondre « Non concerné » doit envoyer à chaque champ SA valeur."""
    cellules = construire_matrice(
        region_code="44",
        en_zar=False,
        en_zone_vulnerable=True,
        axe="fertilisant",
        valeur_figee="cine_avant_3112",
        referentiels=load_referentiels(),
        dates=dict(DATES_DEFAUT_COUVERT["cine_avant_3112"]),
    )
    plan = next(
        q
        for q in questions_rencontrees(cellules)
        if "plan d'épandage ICPE" in q["texte"]
    )
    # Le même libellé peut correspondre à des valeurs techniques distinctes.
    valeurs = set(plan["valeurs_par_libelle"]["Non concerné"].values())
    assert valeurs, "le libellé doit être traduisible"
    assert all(isinstance(v, (str, bool)) for v in valeurs)


def test_cle_affichage_ignore_ponctuation_et_ordre():
    """Deux rédactions de la même question ne diffèrent parfois que d'une
    virgule (« …animale ou, de la… » vs « …animale, ou de la… ») : elles ne
    doivent pas produire deux contrôles."""
    a = {
        "texte": "Le fertilisant est-il issu d'IAA ou, de la distillation ?",
        "choix": [
            {"valeur": True, "libelle": "Oui"},
            {"valeur": False, "libelle": "Non"},
        ],
    }
    b = {
        "texte": "Le fertilisant est-il issu d'IAA, ou de la distillation ?",
        "choix": [
            {"valeur": "autre", "libelle": "Non"},
            {"valeur": "x", "libelle": "Oui"},
        ],
    }
    assert cle_affichage(a) == cle_affichage(b)

    # Un nombre de choix différent reste une question distincte.
    c = {**a, "choix": a["choix"] + [{"valeur": "z", "libelle": "Sans objet"}]}
    assert cle_affichage(a) != cle_affichage(c)


# ─── Déclinaisons de culture + zonages SIG forçables ───────────────────────


def test_branche_expose_ses_declinaisons():
    """« Autres cultures » regroupe vignes, vergers, maraîchères… : la
    représentante seule masquerait les vignes, que les PAR distinguent."""
    autres = next(c for c in lignes_cultures() if c["id"] == "autres_cultures")
    ids = {v["id"] for v in autres["variantes"]}
    assert len(ids) > 1
    assert "cultures_perennes_vignes" in ids
    for variante in autres["variantes"]:
        assert variante["contexte"]["sous_culture_form"] == variante["id"]
        assert variante["label"], "chaque déclinaison doit être nommée"


def test_zonages_rencontres_listes_pour_forcage():
    cellules = construire_matrice(
        region_code="44",
        en_zar=False,
        en_zone_vulnerable=True,
        axe="fertilisant",
        valeur_figee="autres_cultures",
        referentiels=load_referentiels(),
        dates={},
        variante="cultures_perennes_vignes",
    )
    # L'arbre régional n'est pas toujours actif dans la base de test : on
    # vérifie le contrat (liste de champs dédoublonnée), pas sa longueur.
    zonages = zonages_rencontres(cellules)
    assert zonages == sorted(set(zonages))


def test_vignes_en_zone_atteignent_leurs_propres_regles():
    """Cœur du besoin : sans forçage du zonage, la règle vigne du PAR Grand
    Est est inatteignable et la matrice retombe sur le national."""
    commun = dict(
        region_code="44",
        en_zar=False,
        en_zone_vulnerable=True,
        axe="fertilisant",
        valeur_figee="autres_cultures",
        referentiels=load_referentiels(),
        dates={},
        variante="cultures_perennes_vignes",
    )
    zonages = zonages_rencontres(construire_matrice(**commun))
    if not zonages:
        pytest.skip("aucun arbre régional actif : pas de zonage à forcer")
    zonage = zonages[0]
    hors = construire_matrice(**commun)
    dans = construire_matrice(**commun, reponses={zonage: True})

    def _feuille(cellules, ligne):
        c = next(x for x in cellules if x.ligne_id == ligne)
        return c.chemin[-1] if c.chemin else None

    for ligne in ("type_II", "type_III"):
        assert _feuille(hors, ligne) != _feuille(dans, ligne)
        assert "vigne" in _feuille(dans, ligne)


def test_variante_change_le_resultat(client, django_user_model):
    """Vignes et vergers partagent la branche mais pas les règles."""
    user = django_user_model.objects.create_user(
        email="staff-var@example.org", password="x", is_staff=True, name="Staff"
    )
    client.force_login(user)
    url = reverse("nitrates_admin_matrice_index")
    params = {"territoire": "R44", "axe": "fertilisant", "valeur": "autres_cultures"}

    reponse = client.get(url, params)
    assert reponse.status_code == 200
    zonages = reponse.context["zonages"]
    if not zonages:
        pytest.skip("aucun arbre régional actif : pas de zonage à forcer")
    param_sig = zonages[0]["nom_param"]

    def _segments(variante):
        r = client.get(url, {**params, "variante": variante, param_sig: "1"})
        cellule = next(c for c in r.context["cellules"] if c.ligne_id == "type_II")
        return [(s["couleur"], round(s["width_pct"])) for s in cellule.segments]

    assert _segments("cultures_perennes_vignes") != _segments(
        "cultures_perennes_vergers"
    )


def test_zonage_non_coche_reste_hors_zone(client, django_user_model):
    user = django_user_model.objects.create_user(
        email="staff-sig@example.org", password="x", is_staff=True, name="Staff"
    )
    client.force_login(user)
    response = client.get(
        reverse("nitrates_admin_matrice_index"),
        {
            "territoire": "R44",
            "axe": "fertilisant",
            "valeur": "autres_cultures",
            "variante": "cultures_perennes_vignes",
        },
    )
    assert all(not z["actif"] for z in response.context["zonages"])
    cellule = next(c for c in response.context["cellules"] if c.ligne_id == "type_II")
    assert "vigne" not in (cellule.chemin[-1] if cellule.chemin else "")
