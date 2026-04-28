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
    assert ev.regle.periodes == [{"du": "01/01", "au": "31/12"}]


# ─── Resultats par type de regle ──────────────────────────────────────────


def test_culture_post_0101_type_0_interdiction(setup):
    """Culture recoltee apres le 01/01 + type 0 -> interdit du 15/12 au
    15/01."""
    mou = _moulinette(
        occupation_sol="culture_principale",
        sous_culture="culture_recoltee_apres_0101_hors_colza",
        type_fertilisant="type_0",
    )
    ev = _evaluator(mou)
    assert ev.result == RESULTS.interdit
    assert ev.result_code == "r_post_0101_type_0"
    assert ev.regle.code_prescription == "pc4"


def test_chemin_trace_dans_evaluator(setup):
    """Le chemin doit etre accessible pour debug juriste."""
    mou = _moulinette(
        occupation_sol="culture_principale",
        sous_culture="culture_recoltee_apres_0101_hors_colza",
        type_fertilisant="type_0",
    )
    ev = _evaluator(mou)
    # chemin = ids des noeuds traverses
    assert "n_zvn" in ev.chemin
    assert "q_occupation_sol" in ev.chemin
    assert "r_post_0101_type_0" in ev.chemin


# ─── Resolution catalogue interne (zone_note_5) ────────────────────────────


def test_colza_type_II_zone_note_5_absente_sig(setup):
    """zone_note_5 n'a pas encore de dataset, donc resolution = False
    par defaut. Le parcours descend la branche 'autres' (zone_note_5=false)
    et atteint r_colza_type_II_autres."""
    mou = _moulinette(
        occupation_sol="culture_principale",
        sous_culture="colza",
        type_fertilisant="type_II",
    )
    ev = _evaluator(mou)
    assert ev.result == RESULTS.interdit
    assert ev.result_code == "r_colza_type_II_autres"


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
    assert ev.regle.code_prescription == "pc4"


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

    def fake_parcours(arbre, contexte):
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
