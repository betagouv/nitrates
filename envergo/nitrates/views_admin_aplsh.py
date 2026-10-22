"""Calculette APLSH (page admin exploratoire, POC).

Vue « point de vue agriculteur » : à terme la calculette sera une annexe
du résultat de simulation, pré-remplie par le formulaire (région, couvert
→ plafond, fertilisant). Ici on simule ce contexte par un premier volet
de sélections « pré-remplies », puis un second volet avec les questions
propres à la calculette (date d'apport, teneur N si absente du GREN,
dose envisagée). Cf. aplsh.py pour le moteur.
"""

from datetime import date, datetime
from functools import wraps

from django.conf import settings
from django.http import Http404
from django.shortcuts import render

from envergo.nitrates.aplsh import (
    PLAFOND_EFFLUENTS_ELEVAGE_KG_N_HA,
    calculer,
    resoudre_p_generique,
    saison_apport,
)
from envergo.nitrates.connexion import staff_member_required
from envergo.nitrates.models_aplsh import ReferentielAPLSH
from envergo.nitrates.templatetags.nitrates_tags import _MOIS_PAIRES

# Situations d'épandage du 7e PAN (mesure 1, plafonnement des apports).
# Dans le produit final, la situation viendra de la feuille de l'arbre
# (plafonnement_associe) ; ici on la fait choisir pour simuler.
SITUATIONS = [
    {
        "id": "ci_longue",
        "label": "Couvert d'interculture longue (CINE ou CIE)",
        "plafond": 70,
    },
    {
        "id": "cie_courte",
        "label": "Couvert d'interculture courte (dérobée, CIVE)",
        "plafond": 70,
        "note": "Les apports de type II sont exclus du calcul sur CIE courte.",
    },
    {
        "id": "prairie",
        "label": "Prairie de plus de 6 mois, permanente ou luzerne (dès le 1er septembre)",
        "plafond": 70,
    },
    {
        "id": "derogation_icpe",
        "label": "Dérogation plan d'épandage ICPE autorisation (PC1/PC2)",
        "plafond": 100,
    },
    {
        "id": "effluents_interdiction",
        "label": "Effluents peu chargés en période d'interdiction (PC7-PC9)",
        "plafond": 20,
    },
]

AUTRE_PRODUIT = "__autre__"
# Entrée spéciale POC : engrais azoté minéral (type III). Pas une ligne des
# référentiels GREN (l'APLSH y liste les organiques) ni un ajout à la
# nomenclature publiée : pour un minéral, tout l'azote est sous forme
# minérale, donc p = 1 quelle que soit la saison. La teneur N est saisie
# (ex : ammonitrate 33,5 % = 335 kg N/t).
PRODUIT_MINERAL = "__mineral__"

# Centres par défaut pour la météo tant que l'utilisateur n'a pas cliqué
# sur la carte (dans le produit final : la localisation du formulaire).
CENTRES_REGION = {"44": (48.7, 5.6), "32": (49.95, 2.88)}


def _flottant(txt):
    """Parse tolérant : accepte « 2,8 », « 2.8 », espaces parasites."""
    if txt is None:
        return None
    txt = str(txt).strip().replace(",", ".").replace(" ", "")
    if not txt:
        return None
    try:
        return float(txt)
    except ValueError:
        return None


def _pct_annee_agricole(d, debut):
    """Position % d'une date sur l'année agricole (01/07 → 30/06)."""
    return round(100 * (d - debut).days / 365, 2)


def _segments_frise(
    plafond,
    n_total,
    p_ete,
    p_automne,
    borne_ete,
    date_apport,
    dose=None,
    plafond_total=None,
):
    """Frise « dose max selon la période », sur l'année agricole 12 mois.

    Même langage visuel que le calendrier d'épandage du simulateur
    (calendrier.css) : barre grise = hors fenêtre APLSH, zones vertes =
    fenêtre APLSH avec la dose max de chaque période, ticks aux bornes,
    marqueur sur la date d'apport envisagée.
    """
    from envergo.nitrates.aplsh import parser_jour_mois

    mois_b, jour_b = parser_jour_mois(borne_ete)
    annee = date_apport.year - 1 if date_apport.month < 7 else date_apport.year
    debut = date(annee, 7, 1)
    fin_ete = date(annee, mois_b, jour_b)
    fin_fenetre = date(annee + 1, 1, 15)

    def zone(d1, d2, saison, p):
        r = calculer(plafond, n_total, p, saison, plafond_azote_total=plafond_total)
        return {
            "saison": saison,
            "p": p,
            "dose_max": r.dose_max,
            "dose_max_affichee": r.dose_max_affichee,
            "limite": r.limite,
            # Rouge/vert : la DOSE SAISIE passe-t-elle sur cette période ?
            # (sans dose saisie : None → rendu neutre)
            "autorisee": (None if dose is None else dose <= r.dose_max + 0.05 + 1e-9),
            "start_pct": _pct_annee_agricole(d1, debut),
            "width_pct": round(
                _pct_annee_agricole(d2, debut) - _pct_annee_agricole(d1, debut), 2
            ),
            "centre_pct": round(
                (_pct_annee_agricole(d1, debut) + _pct_annee_agricole(d2, debut)) / 2,
                2,
            ),
        }

    zones = [
        zone(debut, fin_ete, "ete", p_ete),
        zone(fin_ete, fin_fenetre, "automne", p_automne),
    ]
    d = min(max(date_apport, debut), date(annee + 1, 6, 30))
    apport_pct = _pct_annee_agricole(d, debut)
    for z in zones:
        z["actif"] = z["start_pct"] <= apport_pct <= z["start_pct"] + z["width_pct"]
    bornes = [
        {"label": "01/07", "pct": 0, "bord_gauche": True},
        {"label": borne_ete, "pct": _pct_annee_agricole(fin_ete, debut)},
        {"label": "15/01", "pct": _pct_annee_agricole(fin_fenetre, debut)},
        {"label": "30/06", "pct": 100, "bord_droit": True},
    ]
    hors_fenetre = date_apport > fin_fenetre or date_apport < debut
    return {
        "zones": zones,
        "bornes": bornes,
        "apport_pct": apport_pct,
        "hors_fenetre": hors_fenetre,
    }


def poc_aplsh_requis(view_func):
    """404 tant que le flag NITRATES_POC_APLSH n'est pas activé (dev seulement)."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not settings.NITRATES_POC_APLSH:
            raise Http404
        return view_func(request, *args, **kwargs)

    return _wrapped


@poc_aplsh_requis
@staff_member_required
def aplsh_index(request):
    referentiels = list(ReferentielAPLSH.objects.filter(actif=True))
    contexte = {
        "referentiels": referentiels,
        "situations": SITUATIONS,
        "AUTRE_PRODUIT": AUTRE_PRODUIT,
        "mois": _MOIS_PAIRES,
    }
    if not referentiels:
        contexte["erreur"] = (
            "Aucun référentiel APLSH actif — lancer `manage.py seed_aplsh`."
        )
        return render(request, "nitrates_admin/aplsh/index.html", contexte)

    ref_id = request.GET.get("referentiel") or ""
    referentiel = next(
        (r for r in referentiels if str(r.pk) == ref_id), referentiels[0]
    )
    situation_id = request.GET.get("situation") or SITUATIONS[0]["id"]
    situation = next((s for s in SITUATIONS if s["id"] == situation_id), SITUATIONS[0])

    produits = referentiel.produits()
    produit_id = request.GET.get("produit") or ""
    produit = next((p for p in produits if str(p["index"]) == produit_id), None)
    mode_autre = produit_id == AUTRE_PRODUIT and referentiel.tableau_generique_parse
    mode_mineral = produit_id == PRODUIT_MINERAL

    # Volet 2 — questions propres à la calculette
    date_brute = (request.GET.get("date_apport") or "").strip()
    try:
        date_apport = datetime.strptime(date_brute, "%Y-%m-%d").date()
    except ValueError:
        date_apport = date.today()
    n_saisi = _flottant(request.GET.get("n_total"))
    cn = _flottant(request.GET.get("cn"))
    nmin_ntot = _flottant(request.GET.get("nmin_ntot"))
    if nmin_ntot is not None and nmin_ntot > 1:
        nmin_ntot = nmin_ntot / 100  # saisi en %
    dose = _flottant(request.GET.get("dose"))

    resultat = None
    resultat_autre_saison = None
    erreur = ""
    info = ""
    n_total = None
    p_ete = p_automne = None
    borne_ete = referentiel.fin_apports_ete
    unite = ""

    if mode_autre:
        if cn is None or nmin_ntot is None:
            erreur = "Renseigner C/N et Nmin/Ntot (analyse du produit)."
        else:
            ligne = resoudre_p_generique(
                referentiel.tableau_generique_parse, cn, nmin_ntot
            )
            if ligne is None:
                erreur = "Aucune tranche de la grille générique ne couvre ces valeurs."
            else:
                p_ete, p_automne = ligne["p_ete"], ligne["p_automne"]
                n_total = n_saisi
                borne_ete = (
                    referentiel.fin_apports_ete_generique or referentiel.fin_apports_ete
                )
    elif mode_mineral:
        p_ete = p_automne = 1.0
        n_total = n_saisi
        unite = "t"
    elif produit:
        p_ete, p_automne = produit["p_ete"], produit["p_automne"]
        n_total = produit["n_total"] if produit["n_total"] is not None else n_saisi
        unite = produit.get("unite", "")

    suggestion_n = None
    if mode_mineral and n_saisi is None:
        suggestion_n = {
            "texte_court": "ex : ammonitrate 33,5 % = 335",
            "texte": (
                "Teneur de l'étiquette, en kg N par tonne de produit : "
                "ammonitrate 33,5 % → 335 ; urée 46 % → 460 ; "
                "solution azotée 30 % → 300 (par m³)."
            ),
        }
    if produit and produit["n_total"] is None:
        # Fourchette indicative pompée dans les autres référentiels (le GE
        # publie ses teneurs) pour le même fertilisant canonique.
        valeurs = [
            ligne["n_total"]
            for autre in referentiels
            if autre.pk != referentiel.pk
            for ligne in autre.tableau_produits_parse
            if ligne["fertilisant"] == produit["fertilisant"]
            and ligne["n_total"] is not None
        ]
        if valeurs:
            mini, maxi = min(valeurs), max(valeurs)
            fourchette = (
                f"{mini:g}".replace(".", ",")
                if mini == maxi
                else f"{mini:g} à {maxi:g}".replace(".", ",")
            )
            suggestion_n = {
                "texte_court": f"en général {fourchette}",
                "texte": (
                    f"En général {fourchette} kg N par unité pour ce type de "
                    "produit (valeurs du GREN Grand Est, indicatives — "
                    "préférer votre analyse)."
                ),
            }

    unite_n = {"t": "kg N/t", "m3": "kg N/m³"}.get(unite, "kg N/t ou m³")
    unite_dose = {"t": "t/ha", "m3": "m³/ha"}.get(unite, "t ou m³/ha")

    # Garde-fou directive nitrates : 170 kg N/ha/an pour les effluents
    # d'ÉLEVAGE (fumiers, lisiers, composts d'effluents). Pas de borne pour
    # le minéral, les boues/IAA ou un produit générique sur analyse.
    plafond_total = None
    if produit and not mode_mineral:
        from envergo.nitrates.models_referentiels import Fertilisant

        categorie = (
            Fertilisant.objects.filter(identifiant=produit["fertilisant"])
            .values_list("categorie", flat=True)
            .first()
        )
        est_elevage = categorie in ("fumiers", "lisiers") or produit["fertilisant"] in (
            "compost_effluents_elevage",
            "compost_fientes_volailles",
            "effluents_peu_charges_elevage",
        )
        if est_elevage:
            plafond_total = PLAFOND_EFFLUENTS_ELEVAGE_KG_N_HA

    segments = []
    if p_ete is not None and not erreur:
        if n_total is None:
            info = (
                f"Le référentiel {referentiel.get_region_code_display()} ne "
                f"fournit pas la teneur en azote de ce produit : saisir la "
                f"valeur ({unite_n}) de votre analyse ou de l'étiquette."
            )
        else:
            saison = saison_apport(date_apport, borne_ete)
            p = p_ete if saison == "ete" else p_automne
            plafond = situation["plafond"]
            resultat = calculer(
                plafond,
                n_total,
                p,
                saison,
                dose=dose,
                plafond_azote_total=plafond_total,
            )
            autre = "automne" if saison == "ete" else "ete"
            p_autre = p_ete if autre == "ete" else p_automne
            if p_autre != p and p_autre > 0:
                resultat_autre_saison = calculer(
                    plafond,
                    n_total,
                    p_autre,
                    autre,
                    plafond_azote_total=plafond_total,
                )
            segments = _segments_frise(
                plafond,
                n_total,
                p_ete,
                p_automne,
                borne_ete,
                date_apport,
                dose,
                plafond_total,
            )

    contexte.update(
        {
            "referentiel": referentiel,
            "situation": situation,
            "produits": produits,
            "produit": produit,
            "produit_id": produit_id,
            "mode_autre": mode_autre,
            "mode_mineral": mode_mineral,
            "PRODUIT_MINERAL": PRODUIT_MINERAL,
            "besoin_n": (
                (mode_autre or (produit and produit["n_total"] is None))
                and n_saisi is None
            ),
            "date_apport": date_apport,
            "n_saisi": n_saisi,
            "cn": cn,
            "nmin_ntot": nmin_ntot,
            "dose": dose,
            "borne_ete": borne_ete,
            "resultat": resultat,
            "resultat_autre_saison": resultat_autre_saison,
            "erreur": erreur,
            "info": info,
            "unite_n": unite_n,
            "suggestion_n": suggestion_n,
            "unite_dose": unite_dose,
            "segments": segments,
        }
    )
    return render(request, "nitrates_admin/aplsh/index.html", contexte)
