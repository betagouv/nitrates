"""Tests de l'ArbreDecisionEvaluator : branchement parcours + mapping
RESULTS Envergo + resolution catalogue SIG."""

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon

from envergo.evaluations.models import RESULTS
from envergo.geodata.models import MAP_TYPES, Department, Map, Zone
from envergo.moulinette.models import Criterion, Regulation
from envergo.nitrates.models import MoulinetteNitrates

# Reims, dans la map ZV de la fixture.
LNG_REIMS = 4.0345
LAT_REIMS = 49.2583


@pytest.fixture
def setup(db):
    """Crée tout ce qu'il faut : dept Marne, map ZV avec zone couvrant
    Reims, regulation+criterion attaches a la map."""
    Department.objects.create(
        department="51",
        geometry=MultiPolygon(Polygon.from_bbox((3.5, 48.7, 5.0, 49.7))),
    )
    m, _ = Map.objects.get_or_create(
        map_type=MAP_TYPES.zv_nitrates,
        defaults={"name": "ZV test", "description": "test"},
    )
    Zone.objects.create(
        map=m,
        geometry=MultiPolygon(Polygon.from_bbox((3.5, 48.7, 5.0, 49.7))),
        attributes={"CdEuBassin": "FRB1", "NomZoneVul": "Test"},
    )
    regulation, _ = Regulation.objects.get_or_create(
        regulation="directive_nitrates",
        defaults={
            "evaluator": (
                "envergo.nitrates.regulations.directive_nitrates."
                "DirectiveNitratesEvaluator"
            ),
        },
    )
    Criterion.objects.get_or_create(
        regulation=regulation,
        evaluator=(
            "envergo.nitrates.regulations.arbre_decision.ArbreDecisionEvaluator"
        ),
        defaults={
            "backend_title": "Arbre decision",
            "title": "Periodes epandage",
            "activation_map": m,
        },
    )
    return m


def _moulinette(**form_data):
    data = {"lng": LNG_REIMS, "lat": LAT_REIMS, **form_data}
    return MoulinetteNitrates(form_kwargs={"data": data})


def _evaluator(moulinette):
    """Retourne l'unique CriterionEvaluator instancie de la moulinette."""
    regulation = list(moulinette.regulations)[0]
    criteres = list(regulation.criteria.all())
    assert len(criteres) == 1
    return criteres[0]._evaluator


# ─── Cas court-circuit (feuilles directes a la racine de l'arbre) ──────────


def test_zvn_sans_reponses_questions_subsidiaires(setup):
    """En ZV, sans avoir choisi d'occupation_sol, on doit recevoir des
    questions subsidiaires (pas un resultat final)."""
    mou = _moulinette()
    ev = _evaluator(mou)
    assert ev.result == RESULTS.non_disponible
    questions = ev.questions_subsidiaires
    assert questions is not None
    champs = [q.champ for q in questions.questions]
    assert "occupation_sol" in champs


def test_sol_non_cultive_court_circuit(setup):
    mou = _moulinette(occupation_sol="sol_non_cultive")
    ev = _evaluator(mou)
    assert ev.result == RESULTS.interdit
    assert ev.result_code == "r_sol_non_cultive"
    assert ev.regle.type == "interdiction"
    # Bornes annee agricole (cf. #54) : couvre toute l'annee mais s'aligne
    # sur l'axe juil-juin du calendrier d'epandage.
    assert ev.regle.periodes == [{"du": "01/07", "au": "30/06"}]


# ─── Resultats par type de regle ──────────────────────────────────────────


def test_culture_post_0101_type_0_interdiction(setup):
    """Culture recoltee apres le 01/01 + type 0 -> interdit du 15/12 au
    15/01."""
    mou = _moulinette(
        occupation_sol="culture_principale",
        sous_culture="culture_hiver_hors_colza",
        type_fertilisant="type_0",
    )
    ev = _evaluator(mou)
    assert ev.result == RESULTS.interdit
    assert ev.result_code == "r_hiver_hors_colza_type_0"
    # Periode standard culture d'hiver hors colza : 15/12 -> 15/01
    assert ev.regle.periodes == [{"du": "15/12", "au": "15/01"}]


def test_chemin_trace_dans_evaluator(setup):
    """Le chemin doit etre accessible pour debug juriste."""
    mou = _moulinette(
        occupation_sol="culture_principale",
        sous_culture="culture_hiver_hors_colza",
        type_fertilisant="type_0",
    )
    ev = _evaluator(mou)
    # chemin = ids des noeuds traverses
    assert "n_zvn" in ev.chemin
    assert "q_occupation_sol" in ev.chemin
    assert "r_hiver_hors_colza_type_0" in ev.chemin


# ─── Resolution catalogue zone_note_5 (Sud-Ouest + PACA/Occitanie) ────────


def test_colza_type_II_hors_zone_note_5(setup):
    """Sans code INSEE pousse par le front (clic carte non fait), le
    resolver zone_note_5 retombe sur False -> branche `autres`."""
    mou = _moulinette(
        occupation_sol="culture_principale",
        sous_culture="colza",
        type_fertilisant="type_II",
    )
    ev = _evaluator(mou)
    assert ev.result == RESULTS.interdit
    assert ev.regle is not None
    assert ev.regle.regle_id == "r_colza_type_II_autres"


def test_colza_type_II_dans_zone_note_5(setup):
    """Avec un code INSEE en zone Sud-Ouest (Toulouse, Occitanie), on
    atteint la branche note 5 specifique."""
    mou = _moulinette(
        code_insee="31555",
        occupation_sol="culture_principale",
        sous_culture="colza",
        type_fertilisant="type_II",
    )
    ev = _evaluator(mou)
    assert ev.result == RESULTS.interdit
    assert ev.regle is not None
    assert ev.regle.regle_id == "r_colza_type_II_note5"


def test_colza_type_0_interdiction_directe(setup):
    """type_0 atteint une feuille interdiction directement, sans avoir
    besoin de resoudre un catalogue."""
    mou = _moulinette(
        occupation_sol="culture_principale",
        sous_culture="colza",
        type_fertilisant="type_0",
    )
    ev = _evaluator(mou)
    assert ev.result == RESULTS.interdit
    assert ev.result_code == "r_colza_type_0"
    assert ev.regle.periodes == [{"du": "15/12", "au": "15/01"}]


# ─── Stub a_completer ─────────────────────────────────────────────────────


def test_regle_a_completer_force_non_disponible(monkeypatch, setup):
    """Une regle marquee a_completer (stub brouillon) ne doit pas afficher
    un resultat final, on force non_disponible meme si le mapping de type
    aurait donne autre chose. Test via un faux Resultat injecte."""
    from envergo.nitrates.regulations import arbre_decision
    from envergo.nitrates.yaml_tree import Resultat

    fake_resultat = Resultat(
        regle_id="r_test_stub",
        type="interdiction",  # mapping normal -> interdit
        chemin=["n_zvn", "r_test_stub"],
        a_completer=True,  # ... mais a_completer force non_disponible
    )

    def fake_parcours(arbre, contexte, **kw):
        return fake_resultat

    monkeypatch.setattr(arbre_decision, "parcours", fake_parcours)

    mou = _moulinette()
    ev = _evaluator(mou)
    assert ev.result == RESULTS.non_disponible
    assert ev.regle.a_completer is True


# ─── Form additionnel ──────────────────────────────────────────────────────


def test_get_form_retourne_form_avec_questions(setup):
    """Quand on a des questions subsidiaires, get_form() retourne un Form
    Django dynamique avec les bons champs et choices."""
    mou = _moulinette()  # rien de saisi
    ev = _evaluator(mou)
    form = ev.get_form()
    assert form is not None
    assert "occupation_sol" in form.fields
    field = form.fields["occupation_sol"]
    valeurs = [v for v, _ in field.choices]
    assert "sol_non_cultive" in valeurs
    assert "culture_principale" in valeurs


def test_get_form_retourne_none_quand_resultat_atteint(setup):
    """Quand on atteint un Resultat final, pas de form additionnel."""
    mou = _moulinette(occupation_sol="sol_non_cultive")
    ev = _evaluator(mou)
    form = ev.get_form()
    assert form is None


def test_parcours_error_swallowed_to_non_disponible(setup):
    """Une valeur d'URL hors arbre (ex: choix supprime du draft pendant
    l'edition) ne doit PAS lever de 500 -- elle bascule en non_disponible.
    Cas reel : l'utilisateur clique un lien partage avec plan_epandage=icpe_ed
    alors qu'on a renomme la branche en `autre` cote draft.

    On utilise la branche luzerne qui pose effectivement la question
    plan_epandage (cf. test_branche_luzerne).
    """
    mou = _moulinette(
        occupation_sol="culture_principale",
        sous_culture="luzerne",
        type_fertilisant="type_I",
        plan_epandage="valeur_inconnue_pas_dans_l_arbre",
    )
    ev = _evaluator(mou)
    assert ev.result == RESULTS.non_disponible


# ─── Catalogue non resolvable -> non_disponible + catalogue_manquant ───────


def test_catalogue_source_non_sig_non_disponible(monkeypatch, setup):
    """Un BesoinCatalogue avec une source autre que 'sig' (ex 'calcul') n'est
    pas resolvable au MVP : _resoudre_catalogue renvoie la sentinelle et
    l'evaluateur bascule en non_disponible en exposant catalogue_manquant."""
    from envergo.nitrates.regulations import arbre_decision
    from envergo.nitrates.yaml_tree import BesoinCatalogue

    besoin = BesoinCatalogue(
        noeud_id="n_calc",
        champ="zone_calculee",
        source="calcul",  # != sig -> non resolvable
        reference="ref_x",
        chemin_partiel=["n_zvn", "n_calc"],
    )
    monkeypatch.setattr(arbre_decision, "parcours", lambda arbre, ctx, **kw: besoin)

    mou = _moulinette()
    ev = _evaluator(mou)
    assert ev.result == RESULTS.non_disponible
    assert ev.catalogue_manquant is besoin
    assert ev.chemin == ["n_zvn", "n_calc"]


def test_catalogue_sig_sans_resolveur_non_disponible(monkeypatch, setup):
    """Source 'sig' mais reference sans resolveur enregistre -> sentinelle ->
    non_disponible (couvre la branche resolver is None)."""
    from envergo.nitrates.regulations import arbre_decision
    from envergo.nitrates.yaml_tree import BesoinCatalogue

    besoin = BesoinCatalogue(
        noeud_id="n_sig",
        champ="zone_inexistante",
        source="sig",
        reference="reference_sans_resolveur",  # pas dans CATALOGUE_RESOLVERS
    )
    monkeypatch.setattr(arbre_decision, "parcours", lambda arbre, ctx, **kw: besoin)

    mou = _moulinette()
    ev = _evaluator(mou)
    assert ev.result == RESULTS.non_disponible
    assert ev.catalogue_manquant is besoin


def test_resultat_inattendu_force_non_disponible(monkeypatch, setup):
    """parcours() ne devrait retourner que ses dataclasses connues ; un objet
    inattendu doit declencher le filet non_disponible (defense)."""
    from envergo.nitrates.regulations import arbre_decision

    monkeypatch.setattr(arbre_decision, "parcours", lambda arbre, ctx, **kw: object())

    mou = _moulinette()
    ev = _evaluator(mou)
    assert ev.result == RESULTS.non_disponible


def test_boucle_catalogue_garde_fou(monkeypatch, setup):
    """Si parcours() retourne sans cesse un BesoinCatalogue resolvable, le
    garde-fou MAX_ITERATIONS_CATALOGUE coupe la boucle -> non_disponible
    (au lieu de tourner a l'infini)."""
    from envergo.nitrates.regulations import arbre_decision
    from envergo.nitrates.yaml_tree import BesoinCatalogue

    besoin = BesoinCatalogue(
        noeud_id="n_loop", champ="boucle", source="sig", reference="r"
    )
    monkeypatch.setattr(arbre_decision, "parcours", lambda arbre, ctx, **kw: besoin)
    # Le catalogue se resout toujours (valeur arbitraire) -> la boucle ne
    # s'arrete que sur le garde-fou d'iterations.
    monkeypatch.setattr(
        arbre_decision.ArbreDecisionEvaluator,
        "_resoudre_catalogue",
        lambda self, b: "valeur_resolue",
    )

    mou = _moulinette()
    ev = _evaluator(mou)
    assert ev.result == RESULTS.non_disponible


# ─── _contexte_initial : valeurs vides ignorees ────────────────────────────


def test_contexte_ignore_valeurs_vides_du_query_string(setup):
    """Une valeur vide ('') dans le query string n'est pas poussee dans le
    contexte de parcours (couvre le filtre des valeurs vides)."""
    mou = _moulinette(occupation_sol="sol_non_cultive", champ_vide="")
    ev = _evaluator(mou)
    assert "champ_vide" not in ev.contexte


# ─── get_form : pas de questions -> None ────────────────────────────────────


def test_get_form_questions_subsidiaires_vide_retourne_none(setup):
    """Si _questions_subsidiaires existe mais que sa liste de questions est
    vide, get_form() retourne None (branche `if not questions`)."""
    from envergo.nitrates.yaml_tree import QuestionsSubsidiaires

    mou = _moulinette(occupation_sol="sol_non_cultive")
    ev = _evaluator(mou)
    # On force un QuestionsSubsidiaires sans question.
    ev._questions_subsidiaires = QuestionsSubsidiaires(questions=[], chemin_partiel=[])
    assert ev.get_form() is None


# ─── Preview admin d'un brouillon via draft_tree_id ─────────────────────────


def _arbre_zvn_court_circuit(rid):
    """Arbre minimal : racine ZV -> branche True/False, feuille directe."""
    return {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_zvn",
                "champ": "en_zone_vulnerable",
                "source": "sig",
                "reference": "zone_vulnerable_nitrates",
                "branches": [
                    {
                        "valeur": True,
                        "regle": {"id": rid, "type": "interdiction", "message": "x"},
                    },
                    {
                        "valeur": False,
                        "regle": {"id": "r_hors", "type": "non_applicable"},
                    },
                ],
            }
        }
    }


def test_preview_draft_tree_id_charge_le_brouillon_seul(setup):
    """Avec draft_tree_id dans le QS, l'evaluateur previsualise CE brouillon
    seul (pas de cascade). Couvre _load_decision_trees branche draft."""
    from envergo.nitrates.models import DecisionTree

    draft = DecisionTree.objects.create(
        name="brouillon_preview",
        status=DecisionTree.STATUS_DRAFT,
        weight=1,
        contenu=_arbre_zvn_court_circuit("r_draft_preview"),
    )
    mou = _moulinette(draft_tree_id=str(draft.pk))
    ev = _evaluator(mou)
    assert ev.result_code == "r_draft_preview"
    # Un seul candidat (le draft), pas la cascade active.
    assert [c.pk for c in ev.candidats] == [draft.pk]
    # Accesseurs debug exposes.
    assert ev.arbre_courant is not None
    assert isinstance(ev.cascade_trace, list)


def test_preview_draft_tree_id_invalide_fallback_cascade(setup):
    """Un draft_tree_id inexistant -> fallback silencieux sur la cascade
    active (pas de crash)."""
    mou = _moulinette(
        draft_tree_id="999999",
        occupation_sol="sol_non_cultive",
    )
    ev = _evaluator(mou)
    # On retombe sur l'arbre actif packagé -> resultat normal.
    assert ev.result_code == "r_sol_non_cultive"


# ─── _appliquer_resultat : type=mixte resolu sur le regime le plus restrictif ─


def test_mixte_resolu_sur_regime_le_plus_restrictif(monkeypatch, setup):
    """Un Resultat type=mixte : le statut global prend le regime le plus
    restrictif des periodes (interdiction > ... > libre)."""
    from envergo.nitrates.regulations import arbre_decision
    from envergo.nitrates.yaml_tree import Resultat

    res = Resultat(
        regle_id="r_mixte_eval",
        type="mixte",
        chemin=["n_zvn", "r_mixte_eval"],
        periodes=[
            {"du": "01/09", "au": "15/10", "regime": "autorisation_sous_condition"},
            {"du": "15/10", "au": "15/01", "regime": "interdiction"},
        ],
    )
    monkeypatch.setattr(arbre_decision, "parcours", lambda arbre, ctx, **kw: res)

    mou = _moulinette()
    ev = _evaluator(mou)
    # interdiction est le plus restrictif -> RESULTS.interdit.
    assert ev.result == RESULTS.interdit
    assert ev.result_code == "r_mixte_eval"
