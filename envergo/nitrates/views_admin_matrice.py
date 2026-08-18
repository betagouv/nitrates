"""Matrice des calendriers d'épandage (page admin exploratoire).

Reconstruit dynamiquement les matrices « catalogue » des conseillers
agricoles (une culture × tous les types de fertilisants, ou l'inverse) en
rejouant la cascade PAN/PAR/ZAR pour chaque combinaison. Cf. matrice.py
pour le moteur et ses hypothèses (défauts SIG + questions complémentaires).
"""

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render

from envergo.nitrates.matrice import (
    LIGNES_FERTILISANTS,
    construire_matrice,
    lignes_cultures,
)
from envergo.nitrates.models import DecisionTree
from envergo.nitrates.templatetags.nitrates_tags import _MOIS_PAIRES
from envergo.nitrates.yaml_tree import load_referentiels

TERRITOIRES = [
    {"id": "R32", "label": "Hauts-de-France", "region_code": "32", "en_zar": False},
    {"id": "R44", "label": "Grand Est", "region_code": "44", "en_zar": False},
    {"id": "R44_ZAR", "label": "Grand Est — ZAR", "region_code": "44", "en_zar": True},
]

# Ids d'inputs de dates lus par les feuilles calculatrice des couverts. On
# expose les deux dates du couvert (semis + destruction/récolte) comme le
# calendrier dynamique du simulateur ; elles ne jouent que sur les lignes
# couvert (les autres n'ont pas de borne event).
CHAMPS_DATES = [
    {"id": "date_semis_couvert", "label": "Date de semis du couvert"},
    {
        "id": "date_destruction_couvert",
        "label": "Date de destruction / récolte du couvert",
    },
]


@staff_member_required
def matrice_index(request):
    territoire_id = request.GET.get("territoire") or "R32"
    territoire = next(
        (t for t in TERRITOIRES if t["id"] == territoire_id), TERRITOIRES[0]
    )
    en_zv = (request.GET.get("zv") or "oui") != "non"
    axe = request.GET.get("axe") or "fertilisant"
    if axe not in ("fertilisant", "culture"):
        axe = "fertilisant"

    cultures = lignes_cultures()
    if axe == "fertilisant":
        options_valeur = [{"id": c["id"], "label": c["label"]} for c in cultures]
    else:
        options_valeur = [
            {"id": f["id"], "label": f["label"]} for f in LIGNES_FERTILISANTS
        ]
    valeur = request.GET.get("valeur") or ""
    if valeur not in {o["id"] for o in options_valeur}:
        valeur = options_valeur[0]["id"] if options_valeur else ""

    dates = {c["id"]: (request.GET.get(c["id"]) or "").strip() for c in CHAMPS_DATES}
    champs_dates = [{**c, "valeur": dates[c["id"]]} for c in CHAMPS_DATES]

    cellules = []
    erreur = ""
    if valeur:
        try:
            cellules = construire_matrice(
                region_code=territoire["region_code"],
                en_zar=territoire["en_zar"],
                en_zone_vulnerable=en_zv,
                axe=axe,
                valeur_figee=valeur,
                referentiels=load_referentiels(),
                dates=dates,
            )
        except DecisionTree.DoesNotExist:
            erreur = "Aucun arbre actif (PAN manquant ?) : charger les arbres."

    # La matrice n'a de sens que sur des combinaisons couvert si l'axe figé
    # est un couvert (axe fertilisant) ou s'il y a des lignes couvert (axe
    # culture) : on affiche les champs dates dès qu'une cellule calculatrice
    # existe, ou que la culture figée est un couvert.
    montrer_dates = any(c.is_calculatrice for c in cellules) or any(
        d for d in dates.values()
    )

    return render(
        request,
        "nitrates_admin/matrice/index.html",
        {
            "territoires": TERRITOIRES,
            "territoire": territoire,
            "en_zv": en_zv,
            "axe": axe,
            "options_valeur": options_valeur,
            "valeur": valeur,
            "champs_dates": champs_dates,
            "montrer_dates": montrer_dates,
            "cellules": cellules,
            "mois": _MOIS_PAIRES,
            "erreur": erreur,
        },
    )
