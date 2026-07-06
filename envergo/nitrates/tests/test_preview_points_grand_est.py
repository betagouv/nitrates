"""Resolution du point preview pour les combinaisons Grand Est.

Les liens preview doivent tomber dans la BONNE zone selon le chemin / le scope :
  - chemin traversant un catalogue zone_grand_est_1 / _2 -> point (avec
    code_insee !) dans la zone Est correspondante ;
  - scope ZAR -> point dans la couche ZAR (en_zar) ;
  - scope region 44 -> point PAR (ZV + region 44, hors ZAR).

NB : les zones Est se resolvent par code_insee (CSV, present en test) -> on les
verifie via est_zone_grand_est_1/2. ZV/en_zar dependent de couches PostGIS non
chargees dans la DB de test ; on verifie donc que le bon POINT du catalogue est
choisi (lat/lng/code_insee), pas le catalog moulinette (teste ailleurs avec
fixtures geo).
"""

import pytest

from envergo.nitrates.yaml_admin.preview import (
    _POINTS,
    compute_simulator_params,
    point_par_defaut_scope,
)
from envergo.nitrates.zonage_zones_est import est_zone_grand_est_1, est_zone_grand_est_2

pytestmark = pytest.mark.django_db


def _catalogue_grand_est(champ: str) -> dict:
    """Arbre : racine ZV -> branche True -> catalogue SIG `champ` -> regle."""
    return {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_zvn",
                "champ": "en_zone_vulnerable",
                "branches": [
                    {
                        "valeur": True,
                        "noeud": {
                            "type_noeud": "catalogue",
                            "id": "n_zge",
                            "champ": champ,
                            "source": "sig",
                            "reference": champ,
                            "branches": [
                                {
                                    "valeur": "q_suite",
                                    "regle": {"id": "r", "type": "interdiction"},
                                }
                            ],
                        },
                    },
                ],
            }
        }
    }


def test_points_grand_est_existent():
    for name in (
        "par_grand_est",
        "zar_grand_est",
        "zone_grand_est_1",
        "zone_grand_est_2",
    ):
        assert name in _POINTS


def test_point_zge1_resolu_par_le_chemin():
    arbre = _catalogue_grand_est("zone_grand_est_1")
    params = compute_simulator_params(arbre, ("n_zvn", "n_zge"))
    # code_insee present ET dans la Zone Est 1 (pas la Zone Est 2).
    assert est_zone_grand_est_1(params.get("code_insee")) is True
    assert est_zone_grand_est_2(params.get("code_insee")) is False


def test_point_zge2_resolu_par_le_chemin():
    arbre = _catalogue_grand_est("zone_grand_est_2")
    params = compute_simulator_params(arbre, ("n_zvn", "n_zge"))
    assert est_zone_grand_est_2(params.get("code_insee")) is True
    assert est_zone_grand_est_1(params.get("code_insee")) is False


def test_point_par_defaut_scope_zar():
    # Point ZAR du catalogue (en_zar verifie ailleurs avec fixtures geo).
    assert point_par_defaut_scope("zar") == _POINTS["zar_grand_est"]


def test_point_par_defaut_scope_region_44():
    assert point_par_defaut_scope("region", "44") == _POINTS["par_grand_est"]


def test_point_par_defaut_scope_national_none():
    """PAN (ou region sans point connu) : pas de point de scope -> chemin."""
    assert point_par_defaut_scope("national") is None
    assert point_par_defaut_scope("region", "11") is None


def test_point_par_defaut_scope_region_32_hauts_de_france():
    """PAR Hauts-de-France (region 32) : point PAR HdF, PAS le point Grand Est.
    Regression : avant, region != 44 -> None -> fallback ZV national = un point
    Grand Est, donc les liens preview d'un arbre HdF pointaient en Grand Est."""
    point = point_par_defaut_scope("region", "32")
    assert point == _POINTS["par_hauts_de_france"]
    assert point != _POINTS["par_grand_est"]


def test_point_hauts_de_france_existe():
    assert "par_hauts_de_france" in _POINTS


def test_point_par_defaut_scope_zar_region_inconnue_reste_grand_est():
    """Forward compat ZAR : le seul ZAR existant est Grand Est. Une region ZAR
    sans point dedie retombe sur le ZAR Grand Est (pas de regression), et un
    ZAR region 44 explicite donne bien le point Grand Est."""
    assert point_par_defaut_scope("zar", "44") == _POINTS["zar_grand_est"]
    assert point_par_defaut_scope("zar", "32") == _POINTS["zar_grand_est"]


def test_chemin_zge_prime_sur_override_scope():
    """Le chemin (ZGE1) prime sur le point par defaut du scope (ex ZAR) : sinon
    un arbre ZAR previsualiserait toujours le centre ZAR meme sur une branche
    Zone Est 1."""
    arbre = _catalogue_grand_est("zone_grand_est_1")
    override = point_par_defaut_scope("zar")  # point ZAR
    params = compute_simulator_params(
        arbre, ("n_zvn", "n_zge"), point_override=override
    )
    # Le code_insee doit etre celui de la Zone Est 1, pas le point ZAR (insee vide).
    assert est_zone_grand_est_1(params.get("code_insee")) is True
