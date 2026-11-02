"""Serveur MCP (/mcp/) : protocole JSON-RPC, flag, lockdown, outils.

Le géocodage (API publiques de l'État) est remplacé par des doublures : les
tests ne sortent jamais sur le réseau.
"""

import base64
import json
import re

import pytest
import yaml as pyyaml
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.utils import timezone

from envergo.geodata.models import MAP_TYPES, Department, Map, Zone
from envergo.moulinette.models import Criterion, Regulation
from envergo.nitrates.mcp import geocodage, images, services
from envergo.nitrates.models import DecisionTree
from envergo.nitrates.models_ouverture import DepartementOuverture

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_nitrates")]

LAT, LNG = 49.2583, 4.0345  # Reims
MARNE = {
    "nom": "Reims",
    "code_insee": "51454",
    "codes_postaux": ["51100"],
    "departement": "Marne",
    "code_departement": "51",
    "population": 180000,
    "lat": LAT,
    "lng": LNG,
}

ARBRE = {
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
                    "noeud": {
                        "type_noeud": "formulaire",
                        "id": "q_sc",
                        "champ": "sous_culture",
                        "niveau": "sous_culture",
                        "texte": "Culture ?",
                        "branches": [
                            {
                                "valeur": "colza",
                                "noeud": {
                                    "type_noeud": "formulaire",
                                    "id": "q_plan",
                                    "champ": "plan_epandage",
                                    "niveau": "complement",
                                    "texte": "Plan d'épandage ICPE ?",
                                    "branches": [
                                        {
                                            "valeur": "icpe_a",
                                            "regle": {
                                                "id": "r_colza_icpe",
                                                "type": "mixte",
                                                "code_prescription": "pc1",
                                                "periodes": [
                                                    {
                                                        "du": "15/10",
                                                        "au": "14/11",
                                                        "regime": "autorisation_sous_condition",
                                                    },
                                                    {
                                                        "du": "15/11",
                                                        "au": "15/01",
                                                        "regime": "interdiction",
                                                    },
                                                ],
                                            },
                                        },
                                        {
                                            "valeur": "icpe_autre",
                                            "regle": {
                                                "id": "r_colza",
                                                "type": "interdiction",
                                                "periodes": [
                                                    {"du": "15/10", "au": "15/01"}
                                                ],
                                            },
                                        },
                                    ],
                                },
                            },
                            {
                                "valeur": "culture_printemps",
                                "regle": {
                                    "id": "r_printemps_calc",
                                    "type": "calculatrice",
                                    "inputs_requis": [
                                        {
                                            "id": "date_semis_couvert",
                                            "type": "date",
                                            "label": "Date de semis du couvert",
                                        }
                                    ],
                                    "periodes": [
                                        {
                                            "du": "date_semis_couvert",
                                            "au": "date_semis_couvert+4semaines",
                                            "regime": "interdiction",
                                        }
                                    ],
                                },
                            },
                        ],
                    },
                },
                {
                    "valeur": False,
                    "regle": {"id": "r_hors_zv", "type": "non_applicable"},
                },
            ],
        }
    }
}


def _rpc(client, method, params=None, id_=1):
    message = {"jsonrpc": "2.0", "method": method}
    if id_ is not None:
        message["id"] = id_
    if params is not None:
        message["params"] = params
    return client.post(
        "/mcp/", data=json.dumps(message), content_type="application/json"
    )


def _appel(client, outil, **arguments):
    reponse = _rpc(client, "tools/call", {"name": outil, "arguments": arguments})
    assert reponse.status_code == 200
    return reponse.json()["result"]


# Domaines que la vue a le droit de charger (Leaflet, tuiles du Plan IGN).
DOMAINES_VUE = ["https://cdnjs.cloudflare.com", "https://data.geopf.fr"]


@pytest.fixture
def mcp_actif(settings):
    settings.NITRATES_MCP = True
    return settings


@pytest.fixture(autouse=True)
def cache_vide():
    """Le serveur garde en cache zonages et géocodage : repartir de zéro."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def sans_tuiles(monkeypatch):
    """Cartes rendues sans fond IGN : pas d'appel réseau en test."""
    monkeypatch.setattr(images, "_tuile", lambda z, x, y: None)


@pytest.fixture
def geocodage_marne(monkeypatch):
    monkeypatch.setattr(geocodage, "commune_par_code", lambda code: dict(MARNE))
    monkeypatch.setattr(geocodage, "commune_au_point", lambda lat, lng: dict(MARNE))
    monkeypatch.setattr(geocodage, "contour_commune", lambda code: None)
    monkeypatch.setattr(geocodage, "chercher_communes", lambda **kw: [dict(MARNE)])


@pytest.fixture
def parcelle_marne(mcp_actif, geocodage_marne):
    """Marne ouverte, en ZV, critère arbre de décision branché, arbre de test
    actif."""
    bbox = MultiPolygon(Polygon.from_bbox((3.5, 48.5, 5.0, 49.7)), srid=4326)
    Department.objects.create(department="51", geometry=bbox)
    DepartementOuverture.objects.update_or_create(
        code="51", defaults={"est_ouvert": True}
    )
    # Même couche que le critère « arbre de décision » déjà en base (cf.
    # test_branche_colza) : sinon le critère ne s'active pas sur la zone.
    carte, _ = Map.objects.get_or_create(
        map_type=MAP_TYPES.zv_nitrates,
        defaults={"name": "ZV test", "description": "test"},
    )
    Zone.objects.create(map=carte, geometry=bbox, attributes={"CdEuBassin": "FRH"})
    regulation, _ = Regulation.objects.get_or_create(
        regulation="directive_nitrates",
        defaults={
            "evaluator": (
                "envergo.nitrates.regulations.directive_nitrates."
                "DirectiveNitratesEvaluator"
            )
        },
    )
    Criterion.objects.get_or_create(
        regulation=regulation,
        evaluator="envergo.nitrates.regulations.arbre_decision.ArbreDecisionEvaluator",
        defaults={
            "backend_title": "Arbre decision",
            "title": "Periodes epandage",
            "activation_map": carte,
        },
    )
    DecisionTree.objects.filter(status=DecisionTree.STATUS_ACTIVE).delete()
    DecisionTree.objects.create(
        name="arbre_test_mcp",
        status=DecisionTree.STATUS_ACTIVE,
        contenu=ARBRE,
        contenu_yaml_brut=pyyaml.safe_dump(ARBRE),
        activated_at=timezone.now(),
    )


# ─── Protocole ─────────────────────────────────────────────────────────────


def test_flag_eteint_404(client, settings):
    settings.NITRATES_MCP = False
    assert _rpc(client, "ping").status_code == 404


def test_get_405(client, mcp_actif):
    reponse = client.get("/mcp/")
    assert reponse.status_code == 405
    assert "POST" in reponse["Allow"]


def test_sans_slash_aussi(client, mcp_actif):
    reponse = client.post(
        "/mcp",
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
        content_type="application/json",
    )
    assert reponse.json() == {"jsonrpc": "2.0", "id": 1, "result": {}}


@pytest.mark.parametrize(
    "demandee,attendue",
    [
        ("2025-06-18", "2025-06-18"),
        ("2025-03-26", "2025-03-26"),
        ("1999-01-01", "2025-06-18"),
    ],
)
def test_initialize_negocie_la_version(client, mcp_actif, demandee, attendue):
    resultat = _rpc(client, "initialize", {"protocolVersion": demandee}).json()[
        "result"
    ]
    assert resultat["protocolVersion"] == attendue
    assert resultat["capabilities"] == {
        "tools": {"listChanged": False},
        "resources": {"listChanged": False},
    }
    assert resultat["serverInfo"]["name"] == "nitrates"
    assert "pas du conseil" in resultat["instructions"]


def test_notification_202_sans_corps(client, mcp_actif):
    reponse = _rpc(client, "notifications/initialized", id_=None)
    assert reponse.status_code == 202
    assert reponse.content == b""


def test_tools_list(client, mcp_actif):
    outils = _rpc(client, "tools/list").json()["result"]["tools"]
    assert [o["name"] for o in outils] == [
        "localiser_parcelle",
        "lister_cultures",
        "lister_fertilisants",
        "simuler_epandage",
        "comparer_cultures",
        "comparer_fertilisants",
        "calculer_aplsh",
        "lire_prescription",
        "lire_document",
        "chercher_definition",
    ]
    for o in outils:
        assert o["inputSchema"]["type"] == "object"
        assert o["annotations"]["readOnlyHint"] is True
        assert o["description"]


def test_erreurs_jsonrpc(client, mcp_actif):
    assert _rpc(client, "methode/inconnue").json()["error"]["code"] == -32601
    assert (
        _rpc(client, "tools/call", {"name": "nope"}).json()["error"]["code"] == -32602
    )
    reponse = client.post("/mcp/", data="{pas du json", content_type="application/json")
    assert reponse.json()["error"]["code"] == -32700


def test_lot_jsonrpc(client, mcp_actif):
    lot = [
        {"jsonrpc": "2.0", "id": 1, "method": "ping"},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "ping"},
    ]
    reponse = client.post(
        "/mcp/", data=json.dumps(lot), content_type="application/json"
    )
    assert [r["id"] for r in reponse.json()] == [1, 2]


def test_public_en_lockdown(client, mcp_actif):
    mcp_actif.LOCKDOWN_BEHIND_LOGIN = True
    assert _rpc(client, "ping").status_code == 200


def test_ferme_en_lockdown_sans_flag(client, settings):
    settings.NITRATES_MCP = False
    settings.LOCKDOWN_BEHIND_LOGIN = True
    assert _rpc(client, "ping").status_code == 302


# ─── Outils ────────────────────────────────────────────────────────────────


def test_catalogues(client, mcp_actif):
    cultures = _appel(client, "lister_cultures")["structuredContent"]
    ids = [c["id"] for g in cultures["groupes"] for c in g["cultures"]]
    assert "colza" in ids and "sol_non_cultive" in ids
    fertilisants = _appel(client, "lister_fertilisants")["structuredContent"]
    lisier = next(
        f
        for c in fertilisants["categories"]
        for f in c["fertilisants"]
        if f["id"] == "dejection_sans_litiere"
    )
    assert lisier["type"] == "type_II"


def test_culture_inconnue_erreur_metier(client, parcelle_marne):
    resultat = _appel(
        client,
        "simuler_epandage",
        lat=LAT,
        lng=LNG,
        culture="ble_tendre",
        fertilisant="dejection_sans_litiere",
    )
    assert resultat["isError"] is True
    assert "Culture inconnue" in resultat["structuredContent"]["erreur"]


def test_commune_homonyme_demande_laquelle(client, mcp_actif, monkeypatch):
    autre = dict(MARNE, code_insee="02000", departement="Aisne", code_departement="02")
    monkeypatch.setattr(
        geocodage, "chercher_communes", lambda **kw: [dict(MARNE), autre]
    )
    resultat = _appel(client, "localiser_parcelle", commune="Reims")
    assert resultat["isError"] is True
    codes = [
        c["code_insee"] for c in resultat["structuredContent"]["communes_possibles"]
    ]
    assert codes == ["51454", "02000"]


def test_geocodage_indisponible(client, mcp_actif, monkeypatch):
    def panne(**kw):
        raise geocodage.GeocodageIndisponible("timeout")

    monkeypatch.setattr(geocodage, "chercher_communes", panne)
    resultat = _appel(client, "localiser_parcelle", commune="Reims")
    assert resultat["isError"] is True
    assert "indisponible" in resultat["structuredContent"]["erreur"]


def _images(resultat):
    return [c for c in resultat["content"] if c["type"] == "image"]


def test_localiser(client, parcelle_marne):
    resultat = _appel(client, "localiser_parcelle", commune="Reims")
    sortie = resultat["structuredContent"]
    # Par défaut, la carte passe par la vue interactive (_meta), pas en PNG.
    assert _images(resultat) == []
    assert "nitrates/carte" in resultat["_meta"]
    assert sortie["localisation"]["code_insee"] == "51454"
    assert sortie["en_zone_vulnerable"] is True
    assert sortie["simulateur_ouvert_dans_ce_departement"] is True
    assert sortie["programmes_applicables"] == ["Programme d'actions national"]
    assert "a_verifier" in sortie  # point au centre de la commune


def test_simulation_pose_la_question_puis_repond(client, parcelle_marne):
    args = dict(lat=LAT, lng=LNG, culture="colza", fertilisant="dejection_sans_litiere")
    sortie = _appel(client, "simuler_epandage", **args)["structuredContent"]
    assert sortie["statut"] == "questions_complementaires"
    assert sortie["questions"][0]["champ"] == "plan_epandage"

    sortie = _appel(
        client,
        "simuler_epandage",
        **args,
        date="2026-11-01",
        reponses={"plan_epandage": "icpe_a"},
    )["structuredContent"]
    assert sortie["statut"] == "resultat"
    resultat = sortie["resultat"]
    assert resultat["regle"] == "r_colza_icpe"
    assert resultat["a_la_date"]["regime"] == "autorisation_sous_condition"
    # La feuille porte pc1 ; en Grand Est, la rédaction affichée est sa
    # déclinaison régionale (même sélection géo que le simulateur, #147).
    assert [p["code"] for p in resultat["prescriptions"]] == ["pc1_ge"]
    assert resultat["prescriptions"][0]["url"].endswith("/prescription/pc1_ge/")
    assert {"du": "15/11", "au": "15/01", "regime": "interdiction"} in [
        {k: p[k] for k in ("du", "au", "regime")} for p in resultat["calendrier"]
    ]
    assert "plan_epandage=icpe_a" in sortie["lien_simulation"]
    assert "regles_permanentes" in sortie


def test_dates_a_preciser_avant_calendrier(client, parcelle_marne):
    args = dict(lat=LAT, lng=LNG, culture="mais", fertilisant="dejection_sans_litiere")
    sortie = _appel(client, "simuler_epandage", **args, date="01/09")
    resultat = sortie["structuredContent"]["resultat"]
    assert resultat["calendrier"] is None
    assert resultat["dates_a_preciser"][0]["champ"] == "date_semis_couvert"
    assert resultat["a_la_date"]["regime"] == "depend_des_dates_a_preciser"
    assert "rappeler simuler_epandage" in resultat["consigne"]

    sortie = _appel(
        client,
        "simuler_epandage",
        **args,
        date="01/09",
        reponses={"date_semis_couvert": "20/08"},
    )
    resultat = sortie["structuredContent"]["resultat"]
    assert resultat["a_la_date"]["regime"] == "interdiction"
    assert resultat["calendrier"][1] == {
        "du": "20/08",
        "au": "17/09",
        "regime": "interdiction",
        "signification": "épandage interdit",
    }


def test_departement_ferme(client, parcelle_marne):
    DepartementOuverture.objects.filter(code="51").update(est_ouvert=False)
    sortie = _appel(
        client,
        "simuler_epandage",
        lat=LAT,
        lng=LNG,
        culture="colza",
        fertilisant="dejection_sans_litiere",
    )["structuredContent"]
    assert sortie["statut"] == "departement_non_ouvert"


def test_comparer_cultures_regroupe_les_questions(client, parcelle_marne):
    sortie = _appel(
        client,
        "comparer_cultures",
        lat=LAT,
        lng=LNG,
        fertilisant="dejection_sans_litiere",
        date="01/12",
    )["structuredContent"]
    a_preciser = {c["id"] for c in sortie["cultures"]["a_preciser"]}
    assert {"colza", "mais"} <= a_preciser
    champs = [q["champ"] for q in sortie["questions_a_poser"]]
    assert champs.count("plan_epandage") == 1
    assert "regles_permanentes" in sortie

    sortie = _appel(
        client,
        "comparer_cultures",
        lat=LAT,
        lng=LNG,
        fertilisant="dejection_sans_litiere",
        date="01/12",
        reponses={"plan_epandage": "icpe_autre"},
    )["structuredContent"]
    (colza,) = [c for c in sortie["cultures"]["interdit"] if c["id"] == "colza"]
    # Un lien de résultat par culture (pas un formulaire à moitié rempli).
    assert "sous_culture_form=colza" in colza["lien_simulation"]
    assert "plan_epandage=icpe_autre" in colza["lien_simulation"]


def test_reponses_ne_touchent_pas_aux_champs_reserves():
    params = services._reponses_en_parametres(
        {
            "draft_tree_id": "12",
            "occupation_sol": "prairie",
            "fertirrigation": False,
            "date_destruction_couvert": "2026-12-10",
        }
    )
    assert params == {
        "fertirrigation": "false",
        "date_destruction_couvert": "10/12",
        "date_destruction_prevue": "10/12",
    }


@pytest.mark.parametrize(
    "saisie,attendue",
    [("15/2", "15/02"), ("15/02/2027", "15/02"), ("2027-02-15", "15/02")],
)
def test_normaliser_date(saisie, attendue):
    assert services.normaliser_date(saisie) == attendue


def test_blocs_en_texte():
    blocs = [
        {"type": "titre_principal", "data": {"texte": "Titre"}},
        {"type": "paragraphe", "data": {"texte": [{"texte": "gras", "gras": True}]}},
        {
            "type": "liste",
            "data": {"items": [{"texte": "a", "enfants": [{"texte": "b"}]}]},
        },
    ]
    assert services.blocs_en_texte(blocs) == "# Titre\ngras\n- a\n  - b"


def test_elements_manquants_lieu_seul_puis_le_reste(client, mcp_actif):
    sortie = _appel(client, "simuler_epandage", fertilisant="dejection_sans_litiere")[
        "structuredContent"
    ]
    assert sortie["statut"] == "elements_manquants"
    # Le lieu d'abord, seul : tout le reste en dépend.
    assert [m["element"] for m in sortie["manque"]] == ["lieu"]
    sortie = _appel(client, "comparer_cultures", commune="Reims")["structuredContent"]
    assert [m["element"] for m in sortie["manque"]] == ["fertilisant", "date"]


def test_couvert_choisi_par_l_agriculteur(client, parcelle_marne):
    """« CIPAN », « couvert » : récolté ou non, en place après le 1er janvier
    ou non, c'est l'agriculteur qui le dit, en cliquant."""
    sortie = _appel(
        client,
        "simuler_epandage",
        lat=LAT,
        lng=LNG,
        culture="CIPAN",
        fertilisant="dejection_sans_litiere",
    )["structuredContent"]
    assert sortie["statut"] == "choix_a_faire"
    assert sortie["champ"] == "culture"
    valeurs = {c["valeur"] for c in sortie["choix"]}
    assert {
        "couvert_courte_recolte",
        "couvert_non_recolte_toujours_en_place_apres_0101",
    } <= valeurs
    assert "colza" not in valeurs


def test_produit_vague_a_choisir_sauf_choix_unique():
    choix = services.demande_de_choix({"culture": "colza", "fertilisant": "fumier"})
    assert choix["champ"] == "fertilisant"
    assert "fumier_mou_susceptible_ecoulement" in {c["valeur"] for c in choix["choix"]}
    # Un seul engrais minéral : appliqué sans faire cliquer.
    arguments = {"culture": "colza", "fertilisant": "ammonitrate"}
    assert services.demande_de_choix(arguments) is None
    assert arguments["fertilisant"] == "engrais_azote_mineral"
    # Ids précis : rien à demander.
    assert (
        services.demande_de_choix(
            {"culture": "couvert_courte_recolte", "fertilisant": "fumier_volaille"}
        )
        is None
    )


def test_comparer_fertilisants(client, parcelle_marne):
    resultat = _appel(
        client,
        "comparer_fertilisants",
        lat=LAT,
        lng=LNG,
        culture="colza",
        date="01/12",
        reponses={"plan_epandage": "icpe_autre"},
    )
    sortie = resultat["structuredContent"]
    assert sortie["statut"] == "resultat"
    ids = {ligne["id"] for lignes in sortie["types"].values() for ligne in lignes}
    assert {"type_0", "type_Ia", "type_Ib", "type_II", "type_III"} <= ids
    meta = resultat["_meta"]
    assert meta["nitrates/titre"].startswith("Colza")
    assert meta["nitrates/reponses"] == {"plan_epandage": "icpe_autre"}
    assert len(meta["nitrates/rangees"]) == len(ids)


def test_icone_du_serveur(client, mcp_actif):
    info = _rpc(client, "initialize", {"protocolVersion": "2025-11-25"}).json()[
        "result"
    ]["serverInfo"]
    sources = [i["src"] for i in info["icons"]]
    assert sources[0].startswith("data:image/png;base64,")
    assert sources[1].endswith("/mcp/icone.png")
    reponse = client.get("/mcp/icone.png")
    assert reponse.status_code == 200
    assert reponse["Content-Type"] == "image/png"


def test_reference_cadastrale(client, parcelle_marne, monkeypatch):
    appels = []

    def parcelle(code_insee, section, numero):
        appels.append((code_insee, section, numero))
        carre = Polygon.from_bbox((4.030, 49.255, 4.032, 49.257))
        return {
            "geometrie": json.loads(carre.geojson),
            "section": section,
            "numero": numero,
            "commune": "Reims",
            "contenance_m2": 1200,
        }

    monkeypatch.setattr(geocodage, "parcelle_cadastrale", parcelle)
    sortie = _appel(
        client, "localiser_parcelle", commune="Reims", reference_cadastrale="ym 28"
    )["structuredContent"]
    assert appels == [("51454", "YM", "0028")]
    assert sortie["localisation"]["precision"] == "parcelle_cadastrale"
    assert sortie["localisation"]["parcelle"] == "Parcelle YM 28, Reims"
    assert 49.255 < sortie["localisation"]["lat"] < 49.257
    resultat = _appel(client, "localiser_parcelle", reference_cadastrale="YM 28")
    assert resultat["isError"] is True  # sans commune, on ne devine pas


def test_comparer_cultures_renvoie_la_matrice(client, parcelle_marne):
    resultat = _appel(
        client,
        "comparer_cultures",
        lat=LAT,
        lng=LNG,
        fertilisant="dejection_sans_litiere",
        date="01/12",
        reponses={"plan_epandage": "icpe_autre"},
    )
    rangees = {r["libelle"]: r for r in resultat["_meta"]["nitrates/rangees"]}
    assert "sous_culture_form=colza" in rangees["Colza"]["lien"]
    # Les cultures qui attendent une précision sont dessinées, jamais omises.
    mais = rangees["Maïs"]
    assert mais["plages"] is None and "semis" in mais["a_preciser"]


def test_documents_cites_et_lecture(client, mcp_actif, tmp_path, settings):
    from envergo.nitrates.models_referentiels import CodePrescription, LienReference

    (tmp_path / "nitrates" / "documents").mkdir(parents=True)
    (tmp_path / "nitrates" / "documents" / "annexe-test.txt").write_text(
        "Texte de l'annexe.", encoding="utf-8"
    )
    settings.STATICFILES_DIRS = [*settings.STATICFILES_DIRS, str(tmp_path)]
    LienReference.objects.create(
        identifiant="annexe-test",
        url="/static/nitrates/documents/annexe-test.pdf",
        libelle="consultez l'annexe de test (PDF)",
    )
    CodePrescription.objects.update_or_create(
        identifiant="pc_test_mcp",
        defaults={
            "blocs": {
                "blocs": [
                    {
                        "type": "paragraphe",
                        "data": {
                            "texte": [
                                {"texte": "voir "},
                                {"texte": "l'annexe", "lien_ref": "annexe-test"},
                            ]
                        },
                    }
                ]
            }
        },
    )
    sortie = _appel(client, "lire_prescription", code="pc_test_mcp")[
        "structuredContent"
    ]
    assert sortie["documents_cites"][0]["identifiant"] == "annexe-test"
    assert sortie["documents_cites"][0]["titre"] == "L'annexe de test (PDF)"
    sortie = _appel(client, "lire_document", identifiant="annexe-test")[
        "structuredContent"
    ]
    assert sortie["texte"] == "Texte de l'annexe."
    assert sortie["url"].endswith("/static/nitrates/documents/annexe-test.pdf")


# ─── Vue MCP Apps et APLSH ─────────────────────────────────────────────────


def test_vue_declaree_sur_les_outils(client, mcp_actif):
    outils = {
        o["name"]: o for o in _rpc(client, "tools/list").json()["result"]["tools"]
    }
    for nom in ("localiser_parcelle", "simuler_epandage", "comparer_cultures"):
        uri = outils[nom]["_meta"]["ui"]["resourceUri"]
        assert re.fullmatch(r"ui://nitrates/epandage-[0-9a-f]{8}\.html", uri)
        assert outils[nom]["_meta"]["openai/outputTemplate"] == uri
    assert "_meta" not in outils["lister_cultures"]

    (ressource,) = _rpc(client, "resources/list").json()["result"]["resources"]
    contenu = _rpc(client, "resources/read", {"uri": ressource["uri"]}).json()[
        "result"
    ]["contents"][0]
    assert contenu["mimeType"] == "text/html;profile=mcp-app"
    assert "ui/initialize" in contenu["text"]
    assert contenu["_meta"]["ui"]["csp"]["resourceDomains"] == DOMAINES_VUE
    erreur = _rpc(client, "resources/read", {"uri": "ui://autre"}).json()["error"]
    assert erreur["code"] == -32602


def test_donnees_de_carte_reservees_a_la_vue(client, parcelle_marne):
    resultat = _appel(client, "localiser_parcelle", commune="Reims")
    carte = resultat["_meta"]["nitrates/carte"]
    assert carte["zones"] == [] and carte["contour"] is None
    # Le modèle ne reçoit pas ces géométries : ni texte, ni structuredContent.
    assert "nitrates/carte" not in resultat["content"][0]["text"]
    assert "_vue" not in resultat["structuredContent"]


def test_calculer_aplsh(client, parcelle_marne):
    from django.core.management import call_command

    call_command("seed_aplsh", verbosity=0)
    args = dict(
        lat=LAT, lng=LNG, fertilisant="dejection_sans_litiere", date="28/08", dose=30
    )
    sortie = _appel(client, "calculer_aplsh", **args)["structuredContent"]
    assert sortie["statut"] == "elements_manquants"
    assert "Lisier de bovins" in sortie["manque"][0]["choix"]

    sortie = _appel(client, "calculer_aplsh", **args, variante="Lisier de bovins")[
        "structuredContent"
    ]
    # 30 m³ × 2,9 kg N/m³ × 0,65 (apport d'été) = 56,5 kg sous le plafond de 70.
    assert sortie["saison"] == "été"
    assert sortie["aplsh_kg_ha"] == 56.5
    assert sortie["conforme"] is True
    assert sortie["dose_max"] == "37,1 m³/ha"

    sortie = _appel(
        client,
        "calculer_aplsh",
        **args,
        variante="Lisier de bovins",
        plafond_kg_aplsh_ha=35,
    )["structuredContent"]
    assert sortie["conforme"] is False and sortie["depassement_pct"] == 62


def test_images_png_en_option(client, parcelle_marne, settings):
    settings.NITRATES_MCP_IMAGES_PNG = True
    resultat = _appel(client, "localiser_parcelle", commune="Reims")
    (image,) = _images(resultat)
    assert base64.b64decode(image["data"]).startswith(b"\x89PNG")
    url = resultat["structuredContent"]["images"][0]["url"]
    assert client.get(url).status_code == 200


@pytest.fixture
def aire_de_captage(parcelle_marne, monkeypatch):
    """Une aire de captage au sud de la commune (contour de commune simulé)."""
    commune = Polygon.from_bbox((4.00, 49.24, 4.06, 49.28))
    monkeypatch.setattr(
        geocodage, "contour_commune", lambda code: json.loads(commune.geojson)
    )
    couche, _ = Map.objects.get_or_create(
        map_type=MAP_TYPES.zone_action_renforcee,
        defaults={"name": "ZAR test", "description": "test"},
    )
    Zone.objects.create(
        map=couche,
        geometry=MultiPolygon(Polygon.from_bbox((4.00, 49.24, 4.06, 49.25)), srid=4326),
        attributes={"NOMZAR": "AAC TEST", "NOMCOMPL": "AAC TEST 1"},
    )


def test_pas_de_reponse_sans_savoir_si_la_parcelle_est_en_aire_de_captage(
    client, aire_de_captage
):
    args = dict(
        commune="Reims",
        culture="colza",
        fertilisant="dejection_sans_litiere",
        reponses={"plan_epandage": "icpe_autre"},
    )
    resultat = _appel(client, "simuler_epandage", **args)
    sortie = resultat["structuredContent"]
    assert sortie["statut"] == "localisation_a_preciser"
    assert "resultat" not in sortie
    assert sortie["zones_sur_la_carte"][0]["nom"] == "AAC TEST 1"
    assert sortie["hors_zones_possible"] is True
    # Aucune coordonnée à recopier pour simuler à la place de l'agriculteur.
    assert "lat" not in json.dumps(sortie["zones_sur_la_carte"])
    assert "lat" not in sortie["localisation"]
    assert resultat["_meta"]["nitrates/carte"]["zones"][0]["numero"] == 1

    for zone, attendu in (("1", "zone 1 (AAC TEST 1)"), ("hors", "hors aire")):
        sortie = _appel(client, "simuler_epandage", **args, zone=zone)[
            "structuredContent"
        ]
        assert sortie["statut"] == "resultat"
        assert attendu in sortie["localisation"]["zone_choisie"]

    # Les coordonnées du centre de la commune ne contournent pas le garde-fou.
    sortie = _appel(
        client, "simuler_epandage", **args, lat=MARNE["lat"], lng=MARNE["lng"]
    )["structuredContent"]
    assert sortie["statut"] == "localisation_a_preciser"
    resultat = _appel(client, "simuler_epandage", **args, zone="9")
    assert resultat["isError"] is True
    # Même garde-fou pour la comparaison des cultures.
    sortie = _appel(
        client,
        "comparer_cultures",
        commune="Reims",
        fertilisant="dejection_sans_litiere",
        date="01/12",
    )["structuredContent"]
    assert sortie["statut"] == "localisation_a_preciser"


def test_base_indisponible_erreur_d_outil(client, mcp_actif, monkeypatch):
    from django.db import OperationalError

    def panne(*args, **kwargs):
        raise OperationalError("the connection is closed")

    monkeypatch.setattr(services, "catalogue_cultures", panne)
    resultat = _appel(client, "lister_cultures")
    assert resultat["isError"] is True
    assert "indisponible" in resultat["structuredContent"]["erreur"]


def test_csp_au_format_chatgpt(client, mcp_actif):
    contenu = _rpc(client, "resources/read", {"uri": "ui://nitrates/epandage.html"})
    meta = contenu.json()["result"]["contents"][0]["_meta"]
    assert meta["openai/widgetCSP"]["resource_domains"] == DOMAINES_VUE
    assert meta["ui"]["csp"]["resourceDomains"] == DOMAINES_VUE


def test_ancienne_uri_de_la_vue_servie(client, mcp_actif):
    """Un hôte qui a gardé une ancienne version en cache reçoit la vue
    actuelle."""
    contenu = _rpc(
        client, "resources/read", {"uri": "ui://nitrates/epandage-0000abcd.html"}
    ).json()["result"]["contents"][0]
    assert contenu["uri"] == "ui://nitrates/epandage-0000abcd.html"
    assert "ui/initialize" in contenu["text"]
    erreur = _rpc(client, "resources/read", {"uri": "ui://autre/vue.html"}).json()
    assert erreur["error"]["code"] == -32602


def test_limite_sur_les_seuls_appels_d_outils(client, mcp_actif, monkeypatch):
    from envergo.nitrates import views_mcp

    mcp_actif.RATELIMIT_ENABLE = True  # coupé dans les réglages de test
    monkeypatch.setattr(views_mcp, "LIMITE_APPELS_OUTILS", "2/m")
    for _ in range(5):
        assert _rpc(client, "initialize", {}).status_code == 200
    statuts = [
        _rpc(
            client, "tools/call", {"name": "lister_cultures", "arguments": {}}
        ).status_code
        for _ in range(3)
    ]
    assert statuts == [200, 200, 429]
