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
    questions_rencontrees,
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

# Dates par défaut, par branche culturale de couvert. Sans elles, les feuilles
# calculatrice n'ont aucune borne resolvable et la cellule s'affiche 100% verte
# — ce qui se lit « autorisé toute l'année » alors que ça veut dire
# « indéterminé ». On pose donc un scénario plausible cohérent avec la
# sémantique de la branche, que l'utilisateur reste libre d'écraser.
#
# La destruction est la date qui pilote réellement les bornes (« X jours avant
# destruction ») ; le semis ne borne que quelques régimes d'implantation, d'où
# un choix volontairement générique (mi-août, sortie de moisson).
#
# Lecture des identifiants de branche :
#   *_avant_3112 = couvert détruit AVANT le 31/12 (« plus en place après 3112 »)
#   *_apres_0101 = couvert encore en place APRÈS le 01/01
#   *_courte     = interculture courte (implantation et destruction rapprochées)
# Préfixe des paramètres GET portant les réponses aux questions complémen-
# taires, pour qu'un champ d'arbre ne puisse pas entrer en collision avec les
# paramètres du formulaire (territoire, axe, valeur, dates…).
PREFIXE_QC = "qc_"

DATES_DEFAUT_COUVERT = {
    "cie_avant_3112": {
        "date_semis_couvert": "15/08",
        "date_destruction_couvert": "15/12",
    },
    "cine_avant_3112": {
        "date_semis_couvert": "15/08",
        "date_destruction_couvert": "15/12",
    },
    "cie_apres_0101": {
        "date_semis_couvert": "15/08",
        "date_destruction_couvert": "15/02",
    },
    "cine_apres_0101": {
        "date_semis_couvert": "15/08",
        "date_destruction_couvert": "15/02",
    },
    "cie_courte": {
        "date_semis_couvert": "15/07",
        "date_destruction_couvert": "15/09",
    },
    "cine_courte": {
        "date_semis_couvert": "15/07",
        "date_destruction_couvert": "15/09",
    },
}


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
    # Défauts par branche de couvert : appliqués uniquement quand l'utilisateur
    # n'a pas encore touché au formulaire (champ absent de la query string). Un
    # champ présent mais vidé est un choix explicite, on le respecte.
    branche_couvert = valeur if axe == "fertilisant" else ""
    defauts = DATES_DEFAUT_COUVERT.get(branche_couvert, {})
    # La note ne se déclenche que sur la date de destruction : c'est elle qui
    # pilote les bornes des calculatrices. Un semis laissé au défaut pendant
    # que l'utilisateur saisit sa destruction ne doit pas afficher « scénario
    # par défaut », ce serait mensonger.
    dates_par_defaut = False
    for champ, valeur_defaut in defauts.items():
        if champ not in request.GET and not dates[champ]:
            dates[champ] = valeur_defaut
            if champ == "date_destruction_couvert":
                dates_par_defaut = True
    champs_dates = [{**c, "valeur": dates[c["id"]]} for c in CHAMPS_DATES]

    cellules = []
    questions = []
    erreur = ""
    if valeur:
        try:
            base = {
                "region_code": territoire["region_code"],
                "en_zar": territoire["en_zar"],
                "en_zone_vulnerable": en_zv,
                "axe": axe,
                "valeur_figee": valeur,
                "referentiels": load_referentiels(),
                "dates": dates,
            }
            # Passe 1 : sans réponse, pour découvrir les questions complémen-
            # taires du chemin et leurs choix possibles.
            cellules = construire_matrice(**base)
            questions = questions_rencontrees(cellules)

            # Passe 2 : si l'utilisateur a répondu à au moins une question, on
            # rejoue la cascade avec ses réponses. Les valeurs transitent en
            # texte dans l'URL : on les recolle sur le choix d'origine pour
            # retrouver leur type réel (True/False/str).
            reponses = {}
            for question in questions:
                brut = request.GET.get(PREFIXE_QC + question["champ"])
                if brut is None:
                    continue
                for choix in question["choix"]:
                    if str(choix["valeur"]) == brut:
                        reponses[question["champ"]] = choix["valeur"]
                        break
            if reponses:
                cellules = construire_matrice(**base, reponses=reponses)
                # Une question répondue peut ne plus être rencontrée (la
                # réponse change le chemin, donc les QC suivantes). On garde
                # néanmoins le contrôle affiché, sinon l'utilisateur ne peut
                # plus revenir sur son choix : on fusionne les deux passes.
                apres = {q["champ"]: q for q in questions_rencontrees(cellules)}
                fusion = []
                for question in questions:
                    champ = question["champ"]
                    if champ in apres:
                        fusion.append(apres.pop(champ))
                    elif champ in reponses:
                        question["valeur"] = reponses[champ]
                        question["par_defaut"] = False
                        # Plus sur aucun chemin : la réponse a fermé la branche
                        # qui posait la question. On l'affiche sans portée.
                        question["lignes"] = []
                        fusion.append(question)
                fusion.extend(apres.values())
                questions = fusion

            # Le template ne sait pas concaténer : on prépare le nom du
            # paramètre GET et la forme texte de chaque choix (pour comparer
            # avec la valeur retenue et cocher la bonne option).
            for question in questions:
                question["nom_param"] = PREFIXE_QC + question["champ"]
                question["valeur_str"] = str(question["valeur"])
                question["choix_rendus"] = [
                    {
                        "valeur_str": str(choix["valeur"]),
                        "libelle": choix.get("libelle") or str(choix["valeur"]),
                    }
                    for choix in question["choix"]
                ]
        except DecisionTree.DoesNotExist:
            erreur = "Aucun arbre actif (PAN manquant ?) : charger les arbres."

    # Les champs dates sont TOUJOURS rendus (layout stable, le formulaire ne
    # saute pas d'une requête à l'autre) mais désactivés quand aucune ligne
    # de la matrice n'en dépend (aucune cellule calculatrice).
    dates_actives = any(c.depend_dates for c in cellules) or any(
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
            "dates_actives": dates_actives,
            "dates_par_defaut": dates_par_defaut,
            "questions": questions,
            "prefixe_qc": PREFIXE_QC,
            "cellules": cellules,
            "mois": _MOIS_PAIRES,
            "erreur": erreur,
        },
    )
