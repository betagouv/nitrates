"""Sélection géo des codes de prescription (#147).

Trois étages testés :
  1. le résolveur pur (`resoudre_codes_prescription`) sur un référentiel
     dict synthétique : fusions, déclinaisons, fallbacks ;
  2. le branchement bout-en-bout dans l'évaluateur : une feuille PAN
     atteinte pour une parcelle Grand Est affiche la déclinaison GE
     (LE cas décorrélation feuille/arbre qui motive la carte) ;
  3. les garde-fous : modèle (clean), validator (feuille = PC de base),
     data migration (parse des identifiants historiques).
"""

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.exceptions import ValidationError as DjangoValidationError

from envergo.geodata.models import MAP_TYPES, Department, Map, Zone
from envergo.moulinette.models import Criterion, Regulation
from envergo.nitrates.models import CodePrescription, MoulinetteNitrates
from envergo.nitrates.yaml_tree import (
    ValidationError,
    load_referentiels,
    resoudre_codes_prescription,
    validate_arbre,
)
from envergo.nitrates.yaml_tree.loader import invalider_cache_referentiels

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _cache_referentiels_propre():
    """Les tests de ce module créent des CodePrescription : on borne le
    cache process-local du référentiel au test (le rollback de la
    transaction de test ne purge pas le lru_cache)."""
    invalider_cache_referentiels()
    yield
    invalider_cache_referentiels()


# ─── 1. Résolveur pur (référentiel synthétique) ──────────────────────────────

REF = {
    "pc1": {},
    "pc5": {},
    "pc11": {},
    "pc11_hdf": {"scope": "region", "region_code": "32", "variante_de": "pc11"},
    "pc12": {"plafond": True},
    "pc12_zar_ge": {"scope": "zar", "region_code": "44", "variante_de": "pc12"},
    "pc1_pc12": {"composants_fusion": ["pc1", "pc12"]},
    "pc1_pc12_ge": {
        "scope": "region",
        "region_code": "44",
        "variante_de": "pc1_pc12",
    },
    "pc1_pc12_zar_ge": {
        "scope": "zar",
        "region_code": "44",
        "variante_de": "pc1_pc12",
    },
    # PC régionale autonome (pas de base nationale), référencée directement
    # par un arbre régional.
    "pc_ge": {"scope": "region", "region_code": "44"},
}


def _resoudre(codes, region_code=None, en_zar=False, ref=REF):
    return resoudre_codes_prescription(
        codes, ref, region_code=region_code, en_zar=en_zar
    )


def test_identite_sans_geo():
    assert _resoudre(["pc11"]) == ["pc11"]


def test_identite_hors_zone():
    # Pas de déclinaison pc12 pour les Hauts-de-France.
    assert _resoudre(["pc12"], region_code="32") == ["pc12"]


def test_declinaison_regionale():
    assert _resoudre(["pc11"], region_code="32") == ["pc11_hdf"]


def test_declinaison_zar_exige_en_zar_et_region():
    assert _resoudre(["pc12"], region_code="44", en_zar=True) == ["pc12_zar_ge"]
    # En région GE mais hors ZAR : pas de déclinaison region pure -> base.
    assert _resoudre(["pc12"], region_code="44", en_zar=False) == ["pc12"]
    # En ZAR d'une autre région : la déclinaison GE ne s'applique pas.
    assert _resoudre(["pc12"], region_code="32", en_zar=True) == ["pc12"]


def test_fusion_nationale():
    assert _resoudre(["pc1", "pc12"]) == ["pc1_pc12"]


def test_fusion_puis_declinaison():
    assert _resoudre(["pc1", "pc12"], region_code="44") == ["pc1_pc12_ge"]
    assert _resoudre(["pc1", "pc12"], region_code="44", en_zar=True) == [
        "pc1_pc12_zar_ge"
    ]


def test_fusion_position_du_premier_composant():
    # La fusion prend la place du premier composant rencontré.
    assert _resoudre(["pc5", "pc1", "pc12"]) == ["pc5", "pc1_pc12"]
    assert _resoudre(["pc12", "pc5", "pc1"]) == ["pc1_pc12", "pc5"]


def test_fusion_incomplete_non_appliquee():
    assert _resoudre(["pc1"]) == ["pc1"]
    assert _resoudre(["pc1", "pc5"]) == ["pc1", "pc5"]


def test_plus_grande_fusion_prioritaire():
    ref = dict(REF)
    ref["pc1_pc5_pc12"] = {"composants_fusion": ["pc1", "pc12", "pc5"]}
    assert _resoudre(["pc1", "pc12", "pc5"], ref=ref) == ["pc1_pc5_pc12"]


def test_pc_regionale_autonome_referencee_directement():
    # Référencée en dur par une feuille d'arbre régional : affichée telle
    # quelle (fallback), où que soit la parcelle.
    assert _resoudre(["pc_ge"], region_code="44") == ["pc_ge"]
    assert _resoudre(["pc_ge"], region_code="32") == ["pc_ge"]


def test_dedoublonnage_et_ordre():
    assert _resoudre(["pc12", "pc12", "pc11"]) == ["pc12", "pc11"]


def test_code_inconnu_conserve():
    assert _resoudre(["pc_inconnu"]) == ["pc_inconnu"]


def test_liste_vide():
    assert _resoudre([]) == []


# ─── 2. Bout-en-bout : évaluateur + géo réelle ───────────────────────────────

# Reims (Marne, 51) -> région 44 Grand Est.
LNG_REIMS = 4.0345
LAT_REIMS = 49.2583

ARBRE_MINI = """
arbre:
  noeud:
    type_noeud: catalogue
    id: n_zvn
    champ: en_zone_vulnerable
    source: sig
    reference: zv_nitrates
    branches:
      - valeur: true
        regle:
          id: r_test
          type: interdiction
          code_prescription: [pc1, pc4]
"""


@pytest.fixture
def setup_geo(db):
    """Département Marne + map ZV couvrant Reims + criterion arbre."""
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


def _evaluator(**form_data):
    data = {"lng": LNG_REIMS, "lat": LAT_REIMS, **form_data}
    moulinette = MoulinetteNitrates(form_kwargs={"data": data})
    regulation = list(moulinette.regulations)[0]
    criteres = list(regulation.criteria.all())
    assert len(criteres) == 1
    return criteres[0]._evaluator


def test_feuille_pan_declinee_pour_parcelle_grand_est(setup_geo, make_active_tree):
    """LE cas qui motive la carte : la feuille appartient au PAN (aucun
    arbre régional en jeu), mais la parcelle est en Grand Est -> la
    déclinaison GE de la PC s'affiche à la place de la base."""
    make_active_tree(ARBRE_MINI)
    CodePrescription.objects.create(
        identifiant="pc4_ge",
        texte_court="version GE",
        scope="region",
        region_code="44",
        variante_de=CodePrescription.objects.get(identifiant="pc4"),
    )
    ev = _evaluator()
    assert ev.regle is not None
    assert ev.regle.codes_prescription == ["pc1", "pc4_ge"]
    assert ev.pc_resolution["feuille"] == ["pc1", "pc4"]
    assert ev.pc_resolution["region_code"] == "44"
    assert ev.pc_resolution["en_zar"] is False


def test_feuille_pan_declinee_zar(setup_geo, make_active_tree):
    """Parcelle en ZAR Grand Est -> déclinaison ZAR prioritaire sur la
    déclinaison régionale (poids 20 > 10)."""
    zar_map = Map.objects.create(
        map_type=MAP_TYPES.zone_action_renforcee, name="ZAR test", description="t"
    )
    Zone.objects.create(
        map=zar_map,
        geometry=MultiPolygon(Polygon.from_bbox((3.5, 48.7, 5.0, 49.7))),
    )
    make_active_tree(ARBRE_MINI)
    base = CodePrescription.objects.get(identifiant="pc4")
    CodePrescription.objects.create(
        identifiant="pc4_ge",
        texte_court="version GE",
        scope="region",
        region_code="44",
        variante_de=base,
    )
    CodePrescription.objects.create(
        identifiant="pc4_zar_ge",
        texte_court="version ZAR GE",
        scope="zar",
        region_code="44",
        variante_de=base,
    )
    ev = _evaluator()
    assert ev.regle.codes_prescription == ["pc1", "pc4_zar_ge"]
    assert ev.pc_resolution["en_zar"] is True


def test_fusion_bout_en_bout(setup_geo, make_active_tree):
    """La feuille liste les composants ; la rédaction fusionnée les
    remplace, sans toucher à l'arbre."""
    make_active_tree(ARBRE_MINI)
    fusion = CodePrescription.objects.create(
        identifiant="pc1_pc4", texte_court="rédaction fusionnée"
    )
    fusion.composants_fusion.set(
        CodePrescription.objects.filter(identifiant__in=["pc1", "pc4"])
    )
    ev = _evaluator()
    assert ev.regle.codes_prescription == ["pc1_pc4"]


def test_sans_variante_ni_fusion_identite(setup_geo, make_active_tree):
    """Non-régression : sans déclinaison ni fusion en base, la liste de la
    feuille est affichée telle quelle (et pas de trace de transformation)."""
    make_active_tree(ARBRE_MINI)
    ev = _evaluator()
    assert ev.regle.codes_prescription == ["pc1", "pc4"]
    assert ev.pc_resolution["feuille"] == ev.pc_resolution["affiches"]


# ─── 3. Garde-fous modèle / validator / migration ────────────────────────────


def test_clean_region_requise_hors_national():
    pc = CodePrescription(identifiant="pc_x", texte_court="t", scope="region")
    with pytest.raises(DjangoValidationError, match="code région"):
        pc.full_clean()


def test_clean_pas_de_region_sur_national():
    pc = CodePrescription(
        identifiant="pc_x", texte_court="t", scope="national", region_code="44"
    )
    with pytest.raises(DjangoValidationError, match="pas porter de code région"):
        pc.full_clean()


def test_clean_pas_de_chaine_de_declinaisons():
    base = CodePrescription.objects.get(identifiant="pc4")
    v1 = CodePrescription.objects.create(
        identifiant="pc4_ge",
        texte_court="t",
        scope="region",
        region_code="44",
        variante_de=base,
    )
    v2 = CodePrescription(
        identifiant="pc4_zar_ge",
        texte_court="t",
        scope="zar",
        region_code="44",
        variante_de=v1,
    )
    with pytest.raises(DjangoValidationError, match="PC de base"):
        v2.full_clean()


def test_unicite_declinaison_par_zone():
    from django.db import IntegrityError

    base = CodePrescription.objects.get(identifiant="pc4")
    CodePrescription.objects.create(
        identifiant="pc4_ge",
        texte_court="t",
        scope="region",
        region_code="44",
        variante_de=base,
    )
    with pytest.raises(IntegrityError):
        CodePrescription.objects.create(
            identifiant="pc4_ge_bis",
            texte_court="t",
            scope="region",
            region_code="44",
            variante_de=base,
        )


ARBRE_VALIDATOR = """
arbre:
  noeud:
    type_noeud: catalogue
    id: n_zvn
    champ: en_zone_vulnerable
    source: sig
    reference: zv_nitrates
    branches:
      - valeur: true
        regle:
          id: r_test
          type: interdiction
          code_prescription: {code}
"""


def test_validator_refuse_declinaison_dans_feuille():
    import yaml as pyyaml

    CodePrescription.objects.create(
        identifiant="pc4_ge",
        texte_court="t",
        scope="region",
        region_code="44",
        variante_de=CodePrescription.objects.get(identifiant="pc4"),
    )
    # scope="region" : un arbre partiel suffit (pas de check d'exhaustivité
    # booléenne), le check des références PC est commun à tous les scopes.
    arbre = pyyaml.safe_load(ARBRE_VALIDATOR.format(code="pc4_ge"))
    with pytest.raises(ValidationError, match="déclinaison géographique"):
        validate_arbre(arbre, scope="region")
    # La base, elle, passe.
    validate_arbre(pyyaml.safe_load(ARBRE_VALIDATOR.format(code="pc4")), scope="region")


def test_referentiel_expose_zone_application():
    """loader._build_referentiels pousse scope/région/liens vers le dict
    consommé par le résolveur et les templates."""
    base = CodePrescription.objects.get(identifiant="pc4")
    CodePrescription.objects.create(
        identifiant="pc4_ge",
        texte_court="t",
        scope="region",
        region_code="44",
        variante_de=base,
    )
    fusion = CodePrescription.objects.create(
        identifiant="pc1_pc4", texte_court="fusion"
    )
    fusion.composants_fusion.set(
        CodePrescription.objects.filter(identifiant__in=["pc1", "pc4"])
    )
    invalider_cache_referentiels()
    codes = load_referentiels()["codes_prescription"]
    assert codes["pc4_ge"]["scope"] == "region"
    assert codes["pc4_ge"]["region_code"] == "44"
    assert codes["pc4_ge"]["variante_de"] == "pc4"
    assert codes["pc1_pc4"]["composants_fusion"] == ["pc1", "pc4"]
    # Une PC de base garde une entrée sans clés de zone (défaut national).
    assert "scope" not in codes["pc1"]
    assert "variante_de" not in codes["pc1"]


def test_data_migration_parse_identifiants():
    """La fonction de la migration 0030 remplit scope/région/liens depuis
    les conventions de nommage, et normalise la casse."""
    import importlib

    from django.apps import apps

    mig = importlib.import_module(
        "envergo.nitrates.migrations.0030_codeprescription_remplir_zone_application"
    )

    CodePrescription.objects.create(identifiant="pc77", texte_court="t")
    CodePrescription.objects.create(identifiant="pc78", texte_court="t")
    CodePrescription.objects.create(identifiant="PC77_ZAR_GE", texte_court="t")
    CodePrescription.objects.create(identifiant="PC77_PC78", texte_court="t")
    CodePrescription.objects.create(identifiant="pc77_pc78_hdf", texte_court="t")
    # Régionale sans base nationale (motif pc_ge).
    CodePrescription.objects.create(identifiant="PC_GE", texte_court="t")

    mig.remplir_zone_application(apps, None)

    v = CodePrescription.objects.get(identifiant="pc77_zar_ge")
    assert (v.scope, v.region_code, v.variante_de.identifiant) == (
        "zar",
        "44",
        "pc77",
    )
    f = CodePrescription.objects.get(identifiant="pc77_pc78")
    assert sorted(c.identifiant for c in f.composants_fusion.all()) == [
        "pc77",
        "pc78",
    ]
    fv = CodePrescription.objects.get(identifiant="pc77_pc78_hdf")
    assert (fv.scope, fv.region_code, fv.variante_de.identifiant) == (
        "region",
        "32",
        "pc77_pc78",
    )
    autonome = CodePrescription.objects.get(identifiant="pc_ge")
    assert (autonome.scope, autonome.region_code) == ("region", "44")
    assert autonome.variante_de is None
