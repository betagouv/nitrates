"""Tests du resolver zone_note_5 (Sud-Ouest + PACA/Occitanie) par
code INSEE + integration via l'ArbreDecisionEvaluator."""

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon

from envergo.evaluations.models import RESULTS
from envergo.geodata.models import MAP_TYPES, Department, Map, Zone
from envergo.moulinette.models import Criterion, Regulation
from envergo.nitrates.models import MoulinetteNitrates
from envergo.nitrates.zonage_note_5 import zone_note_5_pour_commune


def test_paca_dept_04_renvoie_true():
    # Aiglun (04001), region 93 PACA -> note 5
    assert zone_note_5_pour_commune("04001") is True


def test_occitanie_dept_31_renvoie_true():
    # Toulouse (31555), region 76 Occitanie -> note 5
    assert zone_note_5_pour_commune("31555") is True


def test_aquitaine_dept_64_renvoie_true():
    # Pau (64445), dept 64 dans la liste Sud-Ouest
    assert zone_note_5_pour_commune("64445") is True


def test_aquitaine_dept_33_renvoie_true():
    # Bordeaux (33063), dept 33 (Gironde)
    assert zone_note_5_pour_commune("33063") is True


def test_dept_24_renvoie_true():
    # Perigueux (24322), dept 24 (Dordogne)
    assert zone_note_5_pour_commune("24322") is True


def test_grand_est_dept_55_renvoie_false():
    # Bannoncourt (55027), region 44 Grand Est (Meuse) -> hors note 5
    assert zone_note_5_pour_commune("55027") is False


def test_normandie_dept_27_renvoie_false():
    assert zone_note_5_pour_commune("27676") is False


def test_dept_voisin_de_la_liste_renvoie_false():
    # Dept 25 (Doubs) : voisin de 24 mais hors liste
    assert zone_note_5_pour_commune("25056") is False


def test_code_insee_inconnu_dans_dept_note_5_renvoie_true():
    """Heuristique de fallback : si la commune n'est pas dans le CSV
    montagne, on resout via les 2 premiers chiffres du code INSEE
    (= dept). Necessaire pour les communes hors zone montagne (la
    grande majorite des communes 24/33/40/47/64)."""
    assert zone_note_5_pour_commune("33999") is True
    assert zone_note_5_pour_commune("64999") is True


def test_code_insee_none_renvoie_false():
    assert zone_note_5_pour_commune(None) is False


def test_code_insee_vide_renvoie_false():
    assert zone_note_5_pour_commune("") is False


@pytest.mark.parametrize(
    "code,attendu",
    [
        ("04001", True),  # PACA
        ("31555", True),  # Occitanie
        ("64445", True),  # 64
        ("47001", True),  # 47
        ("40001", True),  # 40
        ("55027", False),  # Grand Est
        ("75056", False),  # IDF
    ],
)
def test_zone_note_5_param(code, attendu):
    assert zone_note_5_pour_commune(code) is attendu


# ─── Tests d'integration : parcours complet via ArbreDecisionEvaluator ──────


@pytest.fixture
def setup_zv_full(db):
    """Setup minimal pour un parcours en ZV : la map ZV couvre une bbox
    suffisamment large pour contenir aussi bien Bannoncourt (Meuse) que
    Toulouse (Occitanie)."""
    Department.objects.create(
        department="55",
        geometry=MultiPolygon(Polygon.from_bbox((4.8, 48.5, 5.7, 49.7))),
    )
    m, _ = Map.objects.get_or_create(
        map_type=MAP_TYPES.zv_nitrates,
        defaults={"name": "ZV test", "description": "test"},
    )
    Zone.objects.create(
        map=m,
        geometry=MultiPolygon(Polygon.from_bbox((-1.5, 42.5, 7.5, 51.0))),
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


def _evaluator(mou):
    regulation = list(mou.regulations)[0]
    crit = list(regulation.criteria.all())[0]
    return crit._evaluator


@pytest.mark.parametrize(
    "code_insee,lng,lat,regle_attendue",
    [
        # Bannoncourt (Meuse) : hors zone note 5 -> branche autres
        ("55027", 5.45797, 48.95137, "r_colza_type_II_autres"),
        # Toulouse (Occitanie) : zone note 5 -> branche note5
        ("31555", 1.4442, 43.6047, "r_colza_type_II_note5"),
        # Bordeaux (Gironde 33) : zone note 5
        ("33063", -0.5792, 44.8378, "r_colza_type_II_note5"),
    ],
)
def test_parcours_colza_type_II_resoud_zone_note_5(
    setup_zv_full, code_insee, lng, lat, regle_attendue
):
    """Le parcours colza + type_II bute sur le noeud catalogue
    zone_note_5. Selon le code INSEE pousse par le front, on doit
    atteindre la regle r_colza_type_II_note5 (true) ou
    r_colza_type_II_autres (false)."""
    mou = MoulinetteNitrates(
        form_kwargs={
            "data": {
                "lng": lng,
                "lat": lat,
                "code_insee": code_insee,
                "occupation_sol": "culture_principale",
                "sous_culture": "colza",
                "type_fertilisant": "type_II",
            }
        }
    )
    ev = _evaluator(mou)
    assert ev.result == RESULTS.interdit
    assert ev.regle is not None
    assert ev.regle.regle_id == regle_attendue
