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
    cle_affichage,
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

# Préfixe des paramètres GET portant les réponses aux questions complémen-
# taires, pour qu'un champ d'arbre ne puisse pas entrer en collision avec les
# paramètres du formulaire (territoire, axe, valeur, dates…).
PREFIXE_QC = "qc_"


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
            # Les réponses transitent par LIBELLÉ, pas par valeur : un même
            # contrôle pilote plusieurs champs qui codent différemment la même
            # réponse (« Non concerné » = non_concerne | Non | autre |
            # icpe_autre). On traduit via la table du groupe.
            reponses = {}
            for question in questions:
                libelle = request.GET.get(PREFIXE_QC + question["champ"])
                if libelle is None:
                    continue
                par_champ = question["valeurs_par_libelle"].get(libelle)
                if not par_champ:
                    continue  # libellé inconnu (URL forgée) : on ignore
                reponses.update(par_champ)
            if reponses:
                cellules = construire_matrice(**base, reponses=reponses)
                # La LISTE des contrôles reste celle de la passe 1 : une fois
                # répondue, une question n'est plus « rencontrée » (elle est
                # pré-résolue) et disparaîtrait de l'écran, empêchant de
                # revenir sur son choix. On se contente de reporter les
                # réponses de l'utilisateur sur les contrôles déjà connus.
                apres = {cle_affichage(q): q for q in questions_rencontrees(cellules)}
                for question in questions:
                    choisi = request.GET.get(PREFIXE_QC + question["champ"])
                    if choisi and choisi in question["valeurs_par_libelle"]:
                        question["libelle_retenu"] = choisi
                        question["par_defaut"] = False
                    # Portée réactualisée : une question que la nouvelle
                    # cascade ne croise plus n'a plus d'effet sur la matrice.
                    apres_q = apres.get(cle_affichage(question))
                    if apres_q is not None:
                        question["lignes"] = apres_q["lignes"]
                    elif not question["par_defaut"]:
                        question["lignes"] = []
                # Une question qui n'apparaît QUE dans la nouvelle cascade
                # (branche ouverte par la réponse) est ajoutée à la suite. On
                # dédoublonne sur le seul libellé de la question : la branche
                # nouvellement ouverte peut reposer la même question avec des
                # intitulés de choix légèrement différents, ce qui afficherait
                # deux fois le même contrôle.
                connus = {cle_affichage(q) for q in questions}
                questions.extend(
                    q for q in apres.values() if cle_affichage(q) not in connus
                )

            # Le template ne sait pas concaténer : on prépare le nom du
            # paramètre GET et les options, identifiées par leur libellé (la
            # valeur technique diffère d'un champ à l'autre du groupe).
            for question in questions:
                question["nom_param"] = PREFIXE_QC + question["champ"]
                question["choix_rendus"] = [
                    {"libelle": libelle} for libelle in question["valeurs_par_libelle"]
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
