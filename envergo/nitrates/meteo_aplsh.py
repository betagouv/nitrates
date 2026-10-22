"""Widget météo « risque de volatilisation » (POC calculette APLSH).

Croise une prévision multi-modèles (Open-Meteo : GFS, ICON, Météo-France
AROME/ARPEGE, moyenne équipondérée + dispersion inter-modèles) avec la
grille d'évaluation du risque de perte d'efficacité par volatilisation
ammoniacale de l'annexe n° 17 du GREN Hauts-de-France (source COMIFER,
donc de portée générale même si publiée dans l'arrêté HdF).

Critères de la grille (note globale = somme) :
  sol      pH < 7 → 0 ; 7-7,5 → 2 ; > 7,5 → 3
           CEC < 12 meq/100 g → 2 ; ≥ 12 → 0
  couvert  < 50 % → 0 ; ≥ 50 % → -2
  météo    pluie prévue à 3 jours < 10 mm → 4 ; ≥ 10 mm → 0
           vent > 3 Beaufort (~19 km/h) → 2 ; sinon 0
           T° < 6 °C → 0 ; 6-13 °C → 3 ; > 13 °C → 6

Qualité des conditions selon la note et la forme d'engrais (vert = bonnes
conditions, rouge = apport à éviter) :
  ammonitrates       vert < 14, jaune ≥ 14
  urée + inhibiteur  vert < 4, jaune 4-13, orange ≥ 14
  solution azotée    vert < 4, jaune 4-8, orange 9-13, rouge ≥ 14
  urée solide        vert < 4, jaune 4-8, orange 9-13, rouge ≥ 14 (pire cas)

La grille vise les engrais minéraux ; on l'affiche comme indicateur de
fenêtre d'apport, pas comme prescription.
"""

import time

import requests

# Modèles pertinents pour la météo agricole française : AROME/ARPEGE
# (Météo-France, maille fine), ECMWF IFS (le modèle européen de référence,
# socle de la plupart des météos agricoles), ICON (DWD), UKMO (Met Office),
# GFS (NOAA, gardé car très répandu). Météo Blue / Météo Gris agrègent ces
# mêmes modèles, non exposés en accès libre.
MODELES = {
    "meteofrance_seamless": "AROME/ARPEGE (Météo-France)",
    "ecmwf_ifs025": "ECMWF IFS (européen)",
    "icon_seamless": "ICON (DWD, allemand)",
    "ukmo_seamless": "UKMO (Met Office)",
    "gfs_seamless": "GFS (NOAA, américain)",
}

# Créneaux retenus pour le VERDICT « meilleure fenêtre » : heures ouvrables
# d'un chantier d'épandage (dès l'aube). Les créneaux nocturnes restent
# affichés dans le tableau mais ne sont jamais recommandés.
HEURES_VERDICT = range(5, 21)

# Seuils de la grille annexe 17.
SEUIL_PLUIE_3J_MM = 10
SEUIL_VENT_KMH = 19  # > 3 Beaufort

# Garde-fou COMPLÉMENTAIRE (hors grille COMIFER) : au-delà de ce cumul sur
# 3 jours, la pluie n'incorpore plus l'azote, elle l'entraîne (lixiviation
# des nitrates vers les nappes) et sature le sol en eau (dénitrification →
# protoxyde d'azote N2O, ~42 % des émissions de GES agricoles françaises, CITEPA).
# Un jour « pluie excessive » est dégradé d'un cran et jamais recommandé.
SEUIL_PLUIE_EXCESSIVE_MM = 25

DEGRADATION = {"vert": "jaune", "jaune": "orange", "orange": "rouge", "rouge": "rouge"}

FORMES = [
    {
        "id": "ammonitrates",
        "label": "Ammonitrates",
        "seuils": [(14, "vert"), (99, "jaune")],
    },
    {
        "id": "uree_inhibiteur",
        "label": "Urée + inhibiteur d'uréase",
        "seuils": [(4, "vert"), (14, "jaune"), (99, "orange")],
    },
    {
        "id": "solution_azotee",
        "label": "Solution azotée",
        "seuils": [(4, "vert"), (9, "jaune"), (14, "orange"), (99, "rouge")],
    },
    {
        "id": "uree_solide",
        "label": "Urée solide",
        "seuils": [(4, "vert"), (9, "jaune"), (14, "orange"), (99, "rouge")],
    },
]

# Profils de sensibilité à la volatilisation, dérivés du PRODUIT épandu
# (grille annexe 17 : plus la fraction ammoniacale est élevée, plus les
# seuils sont sévères). Les 4 formes minérales de la grille s'y projettent.
PROFILS = {
    "peu_sensible": {
        "label": "faible",
        "seuils": [(14, "vert"), (99, "jaune")],
    },
    "modere": {
        "label": "modérée",
        "seuils": [(4, "vert"), (14, "jaune"), (99, "orange")],
    },
    "sensible": {
        "label": "élevée",
        "seuils": [(4, "vert"), (9, "jaune"), (14, "orange"), (99, "rouge")],
    },
}

FORME_VERS_PROFIL = {
    "ammonitrates": "peu_sensible",
    "uree_inhibiteur": "modere",
    "solution_azotee": "sensible",
    "uree_solide": "sensible",
}

_cache = {}
_CACHE_TTL = 1800  # 30 min


def sol_au_point(lat, lon):
    """pH et texture du sol au point (SoilGrids ISRIC, 0-5 cm, ~250 m).

    Retourne {"ph", "argile", "sable"} ou None si indisponible."""
    cle = ("sol", round(lat, 3), round(lon, 3))
    if cle in _cache:
        quand, valeur = _cache[cle]
        # Échec (None) : on retente après 5 min seulement — l'API ISRIC est
        # capricieuse ; succès : cache 24 h (le sol ne bouge pas).
        ttl = 300 if valeur is None else 86400
        if time.time() - quand < ttl:
            return valeur
    try:
        r = requests.get(
            "https://rest.isric.org/soilgrids/v2.0/properties/query",
            params={
                "lat": lat,
                "lon": lon,
                "property": ["phh2o", "clay", "sand", "soc"],
                "depth": "0-5cm",
                "value": "mean",
            },
            timeout=6,
        )
        r.raise_for_status()
        valeurs = {}
        for couche in r.json()["properties"]["layers"]:
            brut = couche["depths"][0]["values"]["mean"]
            if brut is None:
                _cache[cle] = (time.time(), None)
                return None
            valeurs[couche["name"]] = brut / 10  # d_factor 10
        sol = {
            "ph": valeurs["phh2o"],
            "argile": valeurs["clay"],
            "sable": valeurs["sand"],
            # soc SoilGrids : dg/kg → g/kg (d_factor 10 déjà appliqué)
            "carbone": valeurs.get("soc"),
        }
    except Exception:
        sol = None
    _cache[cle] = (time.time(), sol)
    return sol


def _moyenne(valeurs):
    valeurs = [v for v in valeurs if v is not None]
    return sum(valeurs) / len(valeurs) if valeurs else None


def note_meteo(pluie_3j, vent, temperature):
    note = 4 if pluie_3j < SEUIL_PLUIE_3J_MM else 0
    note += 2 if vent > SEUIL_VENT_KMH else 0
    if temperature is not None and temperature >= 6:
        note += 3 if temperature <= 13 else 6
    return note


# ─── POC Météo : tableau multi-tranches façon « compare » ────────────────────
#
# Colonnes = tranches de 6 h (matin 06-12, après-midi 12-18, soir 18-24) sur
# 7 jours. Pour chaque tranche, 3 scores sur 10 (10 = aucun risque) :
#   volatilisation NH3 : grille annexe 17 projetée sur 0-10 (pluie incorporante
#     à venir sous 72 h, vent, température de la tranche)
#   lixiviation NO3 : cumul de pluie des 72 h suivant la tranche (0 mm → 10,
#     40 mm et plus → 0)
#   ruissellement : intensité horaire max pendant la tranche et les 24 h
#     suivantes (10 mm/h et plus → 0) ; sol gelé (T min ≤ 0 °C) → 0 et rappel
#     réglementaire (épandage interdit sur sol gelé, PAN mesure 1)
# Total = moyenne pondérée, poids selon la sensibilité volatilisation du
# produit (POC, coefficients à caler ensemble).

# Créneaux de 3 h aux heures des bulletins (2 h, 5 h, 8 h… 23 h) : les
# épandages intéressants se jouent souvent très tôt ou très tard.
HEURES_SLOTS = [2, 5, 8, 11, 14, 17, 20, 23]
DUREE_SLOT = 3

POIDS_PAR_PROFIL = {
    "sensible": {
        "volatilisation": 0.40,
        "lixiviation": 0.25,
        "ruissellement": 0.15,
        "denitrification": 0.20,
    },
    "modere": {
        "volatilisation": 0.30,
        "lixiviation": 0.30,
        "ruissellement": 0.15,
        "denitrification": 0.25,
    },
    "peu_sensible": {
        "volatilisation": 0.15,
        "lixiviation": 0.35,
        "ruissellement": 0.20,
        "denitrification": 0.30,
    },
}


def _fetch_horaire(lat, lon):
    cle = ("h", round(lat, 2), round(lon, 2))
    maintenant = time.time()
    if cle in _cache and maintenant - _cache[cle][0] < _CACHE_TTL:
        return _cache[cle][1]
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "hourly": "temperature_2m,precipitation,wind_speed_10m",
            "daily": "sunrise,sunset",
            "models": ",".join(MODELES),
            "forecast_days": 11,
            "timezone": "Europe/Paris",
        },
        timeout=10,
    )
    r.raise_for_status()
    donnees = r.json()
    _cache[cle] = (maintenant, donnees)
    return donnees


def _serie(hourly, variable, modele=None):
    """Série horaire d'UN modèle, ou moyenne équipondérée si modele=None.

    Moyenner des modèles mélange des scénarios physiquement incohérents
    (chacun a sa propre trajectoire de front) : le défaut de la page est
    donc un modèle unique, la moyenne reste disponible explicitement."""
    if modele:
        return hourly.get(f"{variable}_{modele}") or []
    series = [hourly.get(f"{variable}_{m}") for m in MODELES]
    series = [s for s in series if s]
    n = len(hourly["time"])
    return [_moyenne([s[i] if i < len(s) else None for s in series]) for i in range(n)]


def _score_volatilisation(pluie_72h, vent_max, temp_moy, note_ph=0):
    note = note_meteo(pluie_72h, vent_max, temp_moy) + note_ph
    return round(max(10 * (1 - note / 15), 0), 1)


def _score_lixiviation(pluie_72h):
    return round(10 * (1 - min(pluie_72h, 40) / 40), 1)


def _score_ruissellement(intensite_max, gel, facteur=1.0):
    if gel:
        return 0.0
    return round(10 * (1 - min(intensite_max * facteur, 10) / 10), 1)


FACTEURS_TEXTURE = {
    #              lixiviation  dénitrification  ruissellement
    "sableux": {"lixiv": 1.4, "denitr": 0.7, "ruissel": 0.6},
    "argileux": {"lixiv": 0.7, "denitr": 1.3, "ruissel": 1.15},
    "limoneux": {"lixiv": 1.0, "denitr": 1.0, "ruissel": 1.25},
    "franc": {"lixiv": 1.0, "denitr": 1.0, "ruissel": 1.0},
}


def classe_texture(sol):
    if not sol:
        return "franc"
    argile, sable = sol["argile"], sol["sable"]
    limon = max(100 - argile - sable, 0)
    if argile >= 45:
        return "argileux"
    if sable >= 60:
        return "sableux"
    if limon >= 60:
        return "limoneux"
    return "franc"


def _score_denitrification(pluie_72h, temp_moy, facteur=1.0):
    """Dénitrification partielle → N2O : sol saturé d'eau (pluie forte à
    venir sur l'azote frais) ET microbiologie active (températures douces
    à chaudes). Sol froid : activité microbienne faible, risque réduit."""
    if temp_moy is None or temp_moy < 5:
        facteur_temp = 0.2
    elif temp_moy <= 10:
        facteur_temp = 0.6
    else:
        facteur_temp = 1.0
    risque = min(min(pluie_72h, 40) / 40 * facteur_temp * facteur, 1)
    return round(10 * (1 - risque), 1)


def tableau_meteo(lat, lon, profil_id="modere", modele=None, sol=None):
    """Construit le tableau POC Météo : jours × tranches, scores heatmap."""
    try:
        donnees = _fetch_horaire(lat, lon)
    except Exception as e:
        return {"erreur": f"Prévisions indisponibles ({type(e).__name__})."}

    hourly = donnees["hourly"]
    heures = hourly["time"]
    temp = _serie(hourly, "temperature_2m", modele)
    pluie = _serie(hourly, "precipitation", modele)
    vent = _serie(hourly, "wind_speed_10m", modele)
    poids = POIDS_PAR_PROFIL[profil_id]

    ref_soleil = modele or list(MODELES)[0]
    lever = donnees["daily"].get(f"sunrise_{ref_soleil}") or []
    coucher = donnees["daily"].get(f"sunset_{ref_soleil}") or []
    dates_daily = donnees["daily"]["time"]

    jours = []
    meilleur = None
    for d in range(7):
        base = d * 24
        if base + 24 > len(heures):
            break
        date = heures[base][:10]
        soleil = soleil_lever = soleil_coucher = ""
        if date in dates_daily:
            i = dates_daily.index(date)
            if i < len(lever) and lever[i]:
                soleil_lever = lever[i][11:16]
                soleil_coucher = coucher[i][11:16]
                soleil = f"{soleil_lever} → {soleil_coucher}"
        tranches = []
        for h in HEURES_SLOTS:
            label = f"{h} h"
            i1, i2 = base + h, base + h + DUREE_SLOT
            temps_tranche = [t for t in temp[i1:i2] if t is not None]
            if not temps_tranche:
                continue
            temp_moy = sum(temps_tranche) / len(temps_tranche)
            gel = min(temps_tranche) <= 0
            vent_max = max(v for v in vent[i1:i2] if v is not None)
            pluie_tranche = sum(p for p in pluie[i1:i2] if p is not None)
            fin_72h = i1 + 72
            fenetre_72h = [p for p in pluie[i1:fin_72h] if p is not None]
            pluie_72h = sum(fenetre_72h)
            fin_24h = i2 + 24
            fenetre_24h = [p for p in pluie[i1:fin_24h] if p is not None]
            intensite_max = max(fenetre_24h) if fenetre_24h else 0
            note_ph = 0
            if sol:
                # pH : critère de la grille annexe 17 (pH élevé → NH3 favorisé)
                if sol["ph"] > 7.5:
                    note_ph = 3
                elif sol["ph"] >= 7:
                    note_ph = 2
            texture = classe_texture(sol)
            ft = FACTEURS_TEXTURE[texture]
            scores = {
                "volatilisation": _score_volatilisation(
                    pluie_72h, vent_max, temp_moy, note_ph
                ),
                "lixiviation": _score_lixiviation(pluie_72h * ft["lixiv"]),
                "ruissellement": _score_ruissellement(
                    intensite_max, gel, ft["ruissel"]
                ),
                "denitrification": _score_denitrification(
                    pluie_72h, temp_moy, ft["denitr"]
                ),
            }
            total = round(sum(scores[k] * poids[k] for k in scores), 1)
            tranche = {
                "label": label,
                "heure": h,
                "date": date,
                "temp": round(temp_moy),
                "pluie": round(pluie_tranche, 1),
                "pluie_72h": round(pluie_72h, 1),
                "vent": round(vent_max),
                "gel": gel,
                "intensite_max": round(intensite_max, 1),
                "note_ph": note_ph,
                "texture": texture,
                "ft": ft,
                "scores": scores,
                "total": total,
            }
            tranches.append(tranche)
            if h in HEURES_VERDICT and (meilleur is None or total > meilleur["total"]):
                meilleur = tranche
        jours.append(
            {
                "date": date,
                "soleil": soleil,
                "soleil_lever": soleil_lever,
                "soleil_coucher": soleil_coucher,
                "tranches": tranches,
            }
        )

    if not jours:
        return {"erreur": "Prévisions vides."}
    return {
        "jours": jours,
        "meilleur": meilleur,
        "poids": poids,
        "modeles": list(MODELES.values()),
    }
