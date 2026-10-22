"""POC Météo : fenêtres d'épandage scorées (page admin exploratoire).

Page sœur de la calculette APLSH : même volet « contexte de la
simulation » (région, produit, localisation carte, forme d'engrais si
minéral), mais le corps est un tableau de comparaison façon Windy :
colonnes = tranches de 6 h sur 7 jours, lignes météo (température,
pluie, vent) puis lignes heatmap de scores sur 10 par phénomène
(volatilisation NH3, lixiviation NO3, ruissellement) et total pondéré.
Cf. meteo_aplsh.tableau_meteo pour les hypothèses de scoring.
"""

from django.shortcuts import render

from envergo.nitrates.connexion import staff_member_required
from envergo.nitrates.meteo_aplsh import (
    FORME_VERS_PROFIL,
    FORMES,
    MODELES,
    POIDS_PAR_PROFIL,
    PROFILS,
    sol_au_point,
    tableau_meteo,
)
from envergo.nitrates.models_aplsh import ReferentielAPLSH
from envergo.nitrates.models_referentiels import Fertilisant
from envergo.nitrates.views_admin_aplsh import (
    CENTRES_REGION,
    PRODUIT_MINERAL,
    _flottant,
    poc_aplsh_requis,
)

SEUILS_HEATMAP = [(8, "s8"), (6, "s6"), (4, "s4"), (2, "s2"), (0, "s0")]

# ─── Triangle des textures (diagramme ternaire argile/sable/limon) ──────────
# Zones simplifiées (calepinage 4 familles, sans les 17 classes GEPPA) :
# chaque zone est un polygone en coordonnées (argile, sable, limon) sommant
# à 100, converti en pixels par barycentre des 3 sommets du triangle SVG.
_TRI_SOMMETS = {"argile": (150, 18), "sable": (16, 248), "limon": (284, 248)}

ZONES_TEXTURE = [
    {
        "id": "argileux",
        "label": "Argileux",
        "couleur": "#e0946a",
        "poly": [(45, 55, 0), (100, 0, 0), (45, 0, 55)],
        "conseil": (
            "Sol argileux : il retient l'eau — lixiviation atténuée, mais "
            "vigilance saturation (dénitrification, N₂O) et ruissellement "
            "quand il est déjà gorgé d'eau."
        ),
    },
    {
        "id": "sableux",
        "label": "Sableux",
        "couleur": "#eed382",
        "poly": [(0, 100, 0), (40, 60, 0), (0, 60, 40)],
        "conseil": (
            "Sol sableux : très filtrant — vigilance lixiviation des "
            "nitrates, fractionner les apports et viser des cumuls de pluie "
            "modérés après épandage."
        ),
    },
    {
        "id": "limoneux",
        "label": "Limoneux",
        "couleur": "#cfc09b",
        "poly": [(0, 0, 100), (40, 0, 60), (0, 40, 60)],
        "conseil": (
            "Sol limoneux : sensible à la battance (croûte de surface) — "
            "vigilance ruissellement lors des pluies intenses."
        ),
    },
    {
        "id": "franc",
        "label": "Équilibré (franc)",
        "couleur": "#9fd6a2",
        "poly": [
            (40, 60, 0),
            (45, 55, 0),
            (45, 0, 55),
            (40, 0, 60),
            (0, 40, 60),
            (0, 60, 40),
        ],
        "conseil": (
            "Sol équilibré (franc) : pas de vigilance texture particulière, "
            "les critères météo dominent."
        ),
    },
]


def _tri_px(argile, sable, limon):
    """Barycentre (argile, sable, limon) → pixel du triangle SVG."""
    total = (argile + sable + limon) or 1
    a, s_, l_ = argile / total, sable / total, limon / total
    xa, ya = _TRI_SOMMETS["argile"]
    xs, ys = _TRI_SOMMETS["sable"]
    xl, yl = _TRI_SOMMETS["limon"]
    return (
        round(a * xa + s_ * xs + l_ * xl, 1),
        round(a * ya + s_ * ys + l_ * yl, 1),
    )


def triangle_textures(sol):
    """Données du widget triangle : polygones px, point du sol, conseil."""
    zones = []
    for z in ZONES_TEXTURE:
        points = " ".join(f"{x},{y}" for x, y in (_tri_px(*p) for p in z["poly"]))
        zones.append({**z, "points": points})
    if not sol:
        return {
            "zones": zones,
            "point": None,
            "zone_active": None,
            "zone_label": None,
            "conseils": [],
        }
    argile = sol["argile"]
    sable = sol["sable"]
    limon = max(100 - argile - sable, 0)
    x, y = _tri_px(argile, sable, limon)
    if argile >= 45:
        active = "argileux"
    elif sable >= 60:
        active = "sableux"
    elif limon >= 60:
        active = "limoneux"
    else:
        active = "franc"
    conseils = [z["conseil"] for z in ZONES_TEXTURE if z["id"] == active]
    if sol["ph"] > 7.5:
        conseils.append(
            "pH élevé (sol calcaire) : l'ammonium bascule plus facilement en "
            "ammoniac — vigilance volatilisation (critère de la grille "
            "annexe 17, intégré au score)."
        )
    elif sol["ph"] < 6:
        conseils.append(
            "pH acide : volatilisation limitée, mais un pH bas favorise le "
            "N₂O lors des dénitrifications — et pénalise la plupart des "
            "cultures (d'où la pratique du chaulage : un apport de chaux ou "
            "de calcaire broyé pour remonter le pH)."
        )
    return {
        "zones": zones,
        "point": {"x": x, "y": y},
        "limon": round(limon),
        "zone_active": active,
        "zone_label": next(z["label"] for z in ZONES_TEXTURE if z["id"] == active),
        "conseils": conseils,
    }


def _classe_score(score):
    for seuil, classe in SEUILS_HEATMAP:
        if score >= seuil:
            return classe
    return "s0"


@poc_aplsh_requis
@staff_member_required
def meteo_index(request):
    referentiels = list(ReferentielAPLSH.objects.filter(actif=True))
    referentiel = next(
        (
            r
            for r in referentiels
            if str(r.pk) == (request.GET.get("referentiel") or "")
        ),
        referentiels[0] if referentiels else None,
    )
    produits = referentiel.produits() if referentiel else []
    produit_id = request.GET.get("produit") or ""
    produit = next((p for p in produits if str(p["index"]) == produit_id), None)
    mode_mineral = produit_id == PRODUIT_MINERAL

    forme_id = request.GET.get("forme") or "ammonitrates"
    if forme_id not in {f["id"] for f in FORMES}:
        forme_id = "ammonitrates"
    if mode_mineral:
        profil_id = FORME_VERS_PROFIL[forme_id]
        profil_source = "forme d'engrais minéral choisie"
    elif produit:
        type_regl = (
            Fertilisant.objects.filter(identifiant=produit["fertilisant"])
            .values_list("type_reglementaire", flat=True)
            .first()
        )
        if type_regl == "type_II":
            profil_id = "sensible"
            profil_source = "produit de type II (azote majoritairement ammoniacal)"
        else:
            profil_id = "peu_sensible"
            profil_source = (
                "produit de type 0/I (azote organique à minéralisation lente)"
            )
    else:
        profil_id = "modere"
        profil_source = "aucun produit sélectionné (profil moyen)"

    code_region = referentiel.region_code if referentiel else "44"
    defaut = CENTRES_REGION.get(code_region, (48.7, 5.6))
    lat = _flottant(request.GET.get("lat")) or defaut[0]
    lon = _flottant(request.GET.get("lon")) or defaut[1]

    sol_argile = _flottant(request.GET.get("sol_argile"))
    sol_sable = _flottant(request.GET.get("sol_sable"))
    sol_ph = _flottant(request.GET.get("sol_ph"))
    modele = request.GET.get("modele") or "meteofrance_seamless"
    if modele not in MODELES and modele != "moyenne":
        modele = "meteofrance_seamless"
    sol = sol_au_point(lat, lon)
    sol_source = "api"
    if sol_argile is not None and sol_sable is not None:
        # Saisie manuelle (point déplacé sur le triangle) : prioritaire —
        # l'agriculteur connaît sa parcelle mieux que SoilGrids.
        sol = {
            "ph": sol_ph if sol_ph is not None else (sol["ph"] if sol else 6.5),
            "argile": max(min(sol_argile, 100), 0),
            "sable": max(min(sol_sable, 100), 0),
        }
        sol_source = "manuel"
    elif sol is None:
        sol_source = "indisponible"

    def _detail_calcul(t):
        """Substitution numérique des formules pour une tranche (mode avancé)."""
        poids = POIDS_PAR_PROFIL[profil_id]
        sc = t["scores"]
        note = 0
        note += 4 if t["pluie_72h"] < 10 else 0
        note += 2 if t["vent"] > 19 else 0
        if t["temp"] is not None and t["temp"] >= 6:
            note += 3 if t["temp"] <= 13 else 6
        lignes = [
            f"Créneau {t['date'][8:10]}/{t['date'][5:7]} {t['label']} — intrants : "
            f"pluie 72 h = {t['pluie_72h']} mm, vent max = {t['vent']} km/h, "
            f"T° = {t['temp']} °C, intensité max = {t['intensite_max']} mm/h, "
            f"texture {t['texture']} (facteurs lixiv ×{t['ft']['lixiv']:g}, "
            f"dénitr ×{t['ft']['denitr']:g}, ruissel ×{t['ft']['ruissel']:g})"
            + (", gel" if t["gel"] else ""),
            f"volatilisation : note grille = {note} (+ pH {t['note_ph']}) → "
            f"10 × (1 − {note + t['note_ph']}/15) = {sc['volatilisation']}",
            f"lixiviation : 10 × (1 − min({t['pluie_72h']} × "
            f"{t['ft']['lixiv']:g} ; 40)/40) = {sc['lixiviation']}",
            f"ruissellement : 10 × (1 − min({t['intensite_max']} × "
            f"{t['ft']['ruissel']:g} ; 10)/10)"
            + (" ; sol gelé → 0" if t["gel"] else "")
            + f" = {sc['ruissellement']}",
            f"dénitrification : 10 × (1 − min({t['pluie_72h']} ; 40)/40 "
            f"× f(T°) × {t['ft']['denitr']:g}) = {sc['denitrification']}",
            f"total = {poids['volatilisation']}×{sc['volatilisation']} + "
            f"{poids['lixiviation']}×{sc['lixiviation']} + "
            f"{poids['ruissellement']}×{sc['ruissellement']} + "
            f"{poids['denitrification']}×{sc['denitrification']} = {t['total']}",
        ]
        return lignes

    meteo = tableau_meteo(
        lat,
        lon,
        profil_id=profil_id,
        modele=None if modele == "moyenne" else modele,
        sol=sol,
    )
    courbe = None
    if "jours" in meteo:
        # Classes CSS de heatmap posées côté serveur (pas de calcul template).
        tranches_plat = []
        for jour in meteo["jours"]:
            for t in jour["tranches"]:
                t["classes"] = {k: _classe_score(v) for k, v in t["scores"].items()}
                t["classe_total"] = _classe_score(t["total"])
                tranches_plat.append(t)
        if meteo.get("meilleur"):
            meteo["detail_meilleur"] = _detail_calcul(meteo["meilleur"])
            meteo["detail_maintenant"] = _detail_calcul(
                meteo["jours"][0]["tranches"][0]
            )
        # Courbe de température en filigrane (façon Windy) : polyligne SVG
        # sur une grille de 100 unités par tranche, étirée sur la largeur du
        # tableau (preserveAspectRatio none), les valeurs par-dessus.
        temps = [t["temp"] for t in tranches_plat]
        mini, maxi = min(temps), max(temps)
        etendue = (maxi - mini) or 1
        points = []
        for i, t in enumerate(temps):
            x = i * 100 + 50
            y = round(82 - (t - mini) / etendue * 58)  # 82 (froid) → 24 (chaud)
            points.append(f"{x},{y}")
        courbe = {
            "n": len(temps),
            "largeur": len(temps) * 100,
            "points": " ".join(points),
            "aire": f"0,100 {' '.join(points)} {len(temps) * 100},100",
            "tranches": tranches_plat,
        }

    return render(
        request,
        "nitrates_admin/meteo/index.html",
        {
            "referentiels": referentiels,
            "referentiel": referentiel,
            "produits": produits,
            "produit": produit,
            "produit_id": produit_id,
            "mode_mineral": mode_mineral,
            "PRODUIT_MINERAL": PRODUIT_MINERAL,
            "formes": FORMES,
            "forme_id": forme_id,
            "profil_label": PROFILS[profil_id]["label"],
            "profil_source": profil_source,
            "poids": POIDS_PAR_PROFIL[profil_id],
            "lat": lat,
            "lon": lon,
            "meteo": meteo,
            "modele": modele,
            "modeles_choix": [("moyenne", "Moyenne des 3 modèles")]
            + list(MODELES.items()),
            "sol": sol,
            "sol_source": sol_source,
            "triangle": triangle_textures(sol),
            "courbe": courbe,
        },
    )
