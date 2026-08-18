"""Moteur de la matrice des calendriers d'épandage (page admin exploratoire).

Reconstruit, pour un territoire (région × ZV, éventuellement ZAR) et un axe
figé (une culture × tous les types de fertilisants, ou un fertilisant × toutes
les branches culturales), la matrice « catalogue » que les conseillers
agricoles connaissent (cf. cahier des mesures nitrates) : une ligne par
combinaison, 12 mois (année agricole juillet → juin), cases vert/orange/rouge.

Différences avec le simulateur :
  - pas de point lng/lat : la cascade PAN/PAR/ZAR est rejouée avec un catalog
    synthétique (region_code figé, zar_zone_id résolu depuis l'arbre ZAR
    actif) -> aucun hit PostGIS par cellule ;
  - les nœuds catalogue SIG non résolus par le territoire reçoivent un défaut
    (False = « hors zone »), tracé comme hypothèse sur la cellule ;
  - les questions complémentaires reçoivent une réponse par défaut (« non »
    quand une branche de ce type existe), tracée comme hypothèse ;
  - la linéarisation des régimes jour par jour (périodes conditionnelles,
    masques, bornes semis/destruction) est portée ici en Python depuis
    calculatrice-calendrier.js -- les deux implémentations doivent rester
    synchro (mêmes specs : grammaire calculatrice + extension condition).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from envergo.nitrates.templatetags.nitrates_tags import _day_of_year, _parse_jjmm
from envergo.nitrates.yaml_tree import (
    BesoinCatalogue,
    ParcoursError,
    QuestionsSubsidiaires,
    RenvoiArbre,
    Resultat,
    parcours,
    resoudre_codes_prescription,
    select_active_trees,
)

TOTAL_JOURS = 365

# ─── Bornes / conditions (port Python de calculatrice-calendrier.js) ────────

_UNITES_JOURS = {"jours": 1, "semaines": 7, "mois": 30}
_BORNE_RE = re.compile(r"^([a-z][a-z0-9_]*)(?:([+-])(\d+)(jours|semaines|mois))?$")
_DATE_RE = re.compile(r"^\d{2}/\d{2}$")
_TERME = r"\d{2}/\d{2}|[a-z][a-z0-9_]*(?:[+-]\d+(?:jours|semaines|mois))?"
_CONDITION_RE = re.compile(
    r"^\s*(" + _TERME + r")\s*(<=|>=|==|!=|<|>)\s*(" + _TERME + r")\s*$"
)


@dataclass
class _Borne:
    jour: int | None
    jour_raw: int | None
    is_event: bool


def _jjmm_vers_jour_agricole(val: str) -> int | None:
    """'JJ/MM' (ou slug phénologique connu du référentiel) -> index agricole
    [0, 365), 0 = 1er juillet. Réutilise le parseur du calendrier statique
    (fallback date_calendrier pour les évènements phénologiques)."""
    parsed = _parse_jjmm(val)
    if parsed is None:
        return None
    return _day_of_year(*parsed)


def parse_borne(val: str | None, valeurs: dict[str, str]) -> _Borne:
    """Parse une borne YAML (JJ/MM | event | event±Nunit) en index agricole.

    `valeurs` : dates saisies par input id (ex date_semis_couvert='15/08').
    `jour_raw` = index NON replié (peut sortir de [0, 365) via un offset qui
    franchit l'année agricole) -- sert aux comparaisons de condition, cf. le
    bug « 01/07 < semis-15jours » documenté côté JS."""
    if not val:
        return _Borne(None, None, False)
    if _DATE_RE.match(val):
        j = _jjmm_vers_jour_agricole(val)
        return _Borne(j, j, False)
    m = _BORNE_RE.match(val)
    if not m:
        return _Borne(None, None, False)
    event_id = m.group(1)
    val_event = valeurs.get(event_id)
    if val_event:
        jour = _jjmm_vers_jour_agricole(val_event)
    else:
        # Slug phénologique sans saisie : date conventionnelle du référentiel
        # (même fallback que le calendrier statique). None si inconnu.
        jour = None if m.group(2) else _jjmm_vers_jour_agricole(event_id)
    if jour is None:
        return _Borne(None, None, True)
    jour_raw = jour
    if m.group(2):
        sign = 1 if m.group(2) == "+" else -1
        jour_raw = jour + sign * int(m.group(3)) * _UNITES_JOURS[m.group(4)]
        jour = jour_raw % TOTAL_JOURS
    return _Borne(jour, jour_raw, True)


def _aligner_sur_ancre(f: int, a: int) -> int:
    """Ramène `f` au représentant {f, f±365} le plus proche de l'ancre `a`
    (comparaison dans un repère continu autour de l'évènement)."""
    best, best_dist = f, abs(f - a)
    for cand in (f - TOTAL_JOURS, f + TOTAL_JOURS):
        if abs(cand - a) < best_dist:
            best, best_dist = cand, abs(cand - a)
    return best


def _eval_comparaison(raw_cmp: str, valeurs: dict) -> bool:
    m = _CONDITION_RE.match(raw_cmp)
    if not m:
        return True
    pg = parse_borne(m.group(1), valeurs)
    pd = parse_borne(m.group(3), valeurs)
    if pg.jour_raw is None or pd.jour_raw is None:
        return True  # mode permissif (event non saisi)
    gauche = _aligner_sur_ancre(pg.jour_raw, pd.jour_raw)
    droite = _aligner_sur_ancre(pd.jour_raw, pg.jour_raw)
    op = m.group(2)
    return {
        "<": gauche < droite,
        "<=": gauche <= droite,
        ">": gauche > droite,
        ">=": gauche >= droite,
        "==": gauche == droite,
        "!=": gauche != droite,
    }[op]


def _eval_condition(raw_cond: str | None, valeurs: dict) -> bool:
    if not raw_cond:
        return True
    return all(_eval_comparaison(cmp, valeurs) for cmp in raw_cond.split("&&"))


def _fenetre_degeneree(p: dict, valeurs: dict) -> bool:
    """Fenêtre du->au inversée par une date saisie (cf. JS _fenetreDegeneree) :
    neutralisée si au moins une borne est un event. Un wrap volontaire entre
    deux dates fixes (15/10 -> 31/01) est conservé."""
    du = parse_borne(p.get("du"), valeurs)
    au = parse_borne(p.get("au"), valeurs)
    if du.jour_raw is None or au.jour_raw is None:
        return False

    def franchit(b):
        return b.jour_raw < 0 or b.jour_raw >= TOTAL_JOURS

    if franchit(du) or franchit(au):
        inverse = _aligner_sur_ancre(au.jour_raw, du.jour_raw) < du.jour_raw
    else:
        inverse = au.jour < du.jour
    return inverse and (du.is_event or au.is_event)


def _periode_active(p: dict, valeurs: dict) -> bool:
    return _eval_condition(p.get("condition"), valeurs) and not _fenetre_degeneree(
        p, valeurs
    )


SEVERITE_REGIME = {
    "libre": 0,
    "plafonnement": 1,
    "autorisation_sous_condition": 2,
    "interdiction": 3,
    "non_applicable": -1,
}


def compute_regime_par_jour(
    regle_type: str,
    periodes: list[dict],
    valeurs: dict,
    tous_plafonds: bool = False,
) -> list[str]:
    """Tableau des 365 régimes journaliers (port de computeRegimePerDay JS) :
    passe 1 principales (le plus sévère gagne sur chevauchement), passe 2
    masques (sur intersection avec une principale uniquement, anti-artefact
    de jour-frontière), puis règle « 100 % plafond » (ASC repeint en libre)."""
    result = ["libre"] * TOTAL_JOURS
    principal_covers = [False] * TOTAL_JOURS
    masque_regime: list[str | None] = [None] * TOTAL_JOURS
    principal_starts = [0] * TOTAL_JOURS
    principal_ends = [0] * TOTAL_JOURS

    actives = [p for p in (periodes or []) if _periode_active(p, valeurs)]

    def _iter_jours(du: int, au: int):
        if du <= au:
            yield from range(du, au + 1)
        else:
            yield from range(du, TOTAL_JOURS)
            yield from range(0, au + 1)

    for p in actives:
        if p.get("masque"):
            continue
        du = parse_borne(p.get("du"), valeurs).jour
        au = parse_borne(p.get("au"), valeurs).jour
        regime = p.get("regime") or regle_type or "interdiction"
        if du is None or au is None:
            continue
        principal_starts[du] += 1
        principal_ends[au] += 1
        for i in _iter_jours(du, au):
            if not principal_covers[i] or SEVERITE_REGIME.get(
                regime, 0
            ) >= SEVERITE_REGIME.get(result[i], 0):
                result[i] = regime
            principal_covers[i] = True

    for p in actives:
        if not p.get("masque"):
            continue
        du = parse_borne(p.get("du"), valeurs).jour
        au = parse_borne(p.get("au"), valeurs).jour
        regime = p.get("regime") or regle_type or "interdiction"
        if du is None or au is None:
            continue
        for i in _iter_jours(du, au):
            if not principal_covers[i]:
                continue
            if i == du and principal_ends[i] > 0 and principal_starts[i] == 0:
                continue
            if masque_regime[i] is None or SEVERITE_REGIME.get(
                regime, 0
            ) >= SEVERITE_REGIME.get(masque_regime[i], 0):
                result[i] = regime
                masque_regime[i] = regime

    if tous_plafonds:
        result = ["libre" if r == "autorisation_sous_condition" else r for r in result]
    return result


_COULEUR_PAR_REGIME = {
    "interdiction": "rouge",
    "autorisation_sous_condition": "orange",
    "plafonnement": "orange",
    "libre": "vert",
}


def segments_depuis_regimes(regimes: list[str]) -> list[dict]:
    """Fusionne les jours contigus de même couleur en segments % pour le
    rendu de la barre (start_pct / width_pct / couleur / regime)."""
    segments = []
    debut = 0
    couleur_courante = _COULEUR_PAR_REGIME.get(regimes[0], "gris")
    regime_courant = regimes[0]
    for i in range(1, TOTAL_JOURS + 1):
        couleur = (
            _COULEUR_PAR_REGIME.get(regimes[i], "gris") if i < TOTAL_JOURS else None
        )
        if couleur != couleur_courante:
            segments.append(
                {
                    "start_pct": debut / TOTAL_JOURS * 100,
                    "width_pct": (i - debut) / TOTAL_JOURS * 100,
                    "couleur": couleur_courante,
                    "regime": regime_courant,
                }
            )
            debut = i
            if i < TOTAL_JOURS:
                couleur_courante = couleur
                regime_courant = regimes[i]
    return segments


# ─── Cascade sans géo ───────────────────────────────────────────────────────

MAX_TOURS = 40


@dataclass
class Cellule:
    """Résultat d'une combinaison de la matrice."""

    ligne_id: str
    ligne_label: str
    statut: str  # ok | non_disponible | erreur
    regle: Resultat | None = None
    segments: list[dict] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    pcs: list[dict] = field(default_factory=list)  # PC hors plafond (drawer)
    plafonds: list[dict] = field(default_factory=list)  # PC plafond (inline)
    arbre_name: str = ""
    chemin: list[str] = field(default_factory=list)
    detail: str = ""  # message d'explication (statut != ok)
    has_orange: bool = False
    is_calculatrice: bool = False


def _defaut_question(question) -> tuple[object, str] | None:
    """Choisit la réponse par défaut d'une question complémentaire :
    False explicite, puis valeur « non* », puis 1re branche. Retourne
    (valeur, libelle) ou None si pas de choix."""
    choix = question.choix or []
    if not choix:
        return None

    def _libelle(c):
        return c.get("libelle") or str(c["valeur"])

    for c in choix:
        if c["valeur"] is False:
            return c["valeur"], _libelle(c)
    # Cas général « négatif » cherché sur la valeur PUIS le libellé (certaines
    # QC portent des valeurs métier type 'Plan ICPE A' avec un choix négatif
    # identifiable seulement par son libellé « Non... » / « Pas... »).
    for c in choix:
        if str(c["valeur"]).lower().startswith(("non", "pas ")):
            return c["valeur"], _libelle(c)
    for c in choix:
        if _libelle(c).lower().startswith(("non", "pas ")):
            return c["valeur"], _libelle(c)
    return choix[0]["valeur"], _libelle(choix[0])


def evaluer_combinaison(candidats, contexte_initial: dict) -> dict:
    """Rejoue la cascade d'ArbreDecisionEvaluator.evaluate() sans géo.

    Les nœuds catalogue SIG irrésolus reçoivent False (« hors zone »), les
    questions complémentaires une réponse par défaut ; les deux sont tracés
    dans `hypotheses`. Retourne un dict {statut, resultat, hypotheses,
    arbre_name, detail}."""
    contexte = dict(contexte_initial)
    hypotheses: list[str] = []
    restants = list(candidats)
    par_scope = {a.scope: a for a in candidats}
    noeud_depart = None
    dernier_no_match = ""
    candidat = None

    for _ in range(MAX_TOURS):
        if candidat is None:
            if not restants:
                return {
                    "statut": "non_disponible",
                    "resultat": None,
                    "hypotheses": hypotheses,
                    "arbre_name": "",
                    "detail": dernier_no_match or "cascade épuisée",
                }
            candidat = restants.pop(0)
            depart = noeud_depart
            noeud_depart = None
        try:
            res = parcours(candidat.contenu, contexte, noeud_depart=depart)
        except ParcoursError as exc:
            dernier_no_match = str(exc)
            candidat = None
            continue

        if isinstance(res, RenvoiArbre):
            cible = par_scope.get(res.scope_cible)
            if cible is None:
                return {
                    "statut": "non_disponible",
                    "resultat": None,
                    "hypotheses": hypotheses,
                    "arbre_name": candidat.name,
                    "detail": f"renvoi vers scope '{res.scope_cible}' sans arbre actif",
                }
            if res.remap_contexte:
                contexte = dict(contexte)
                contexte.update(res.remap_contexte)
            restants = [a for a in restants if a.scope != res.scope_cible]
            candidat = cible
            depart = res.noeud_cible
            continue

        if isinstance(res, BesoinCatalogue):
            # Pas de géo dans la matrice : défaut « hors zone » (False),
            # tracé comme hypothèse. Si la branche False n'existe pas,
            # le tour suivant lèvera un ParcoursError -> no-match cascade.
            contexte[res.champ] = False
            hypotheses.append(f"{res.champ} : hors zone (défaut SIG)")
            depart = None
            continue

        if isinstance(res, QuestionsSubsidiaires):
            progression = False
            for q in res.questions:
                if contexte.get(q.champ) is not None:
                    continue
                defaut = _defaut_question(q)
                if defaut is None:
                    continue
                valeur, libelle = defaut
                contexte[q.champ] = valeur
                hypotheses.append(f"{q.texte} → {libelle} (défaut)")
                progression = True
            if not progression:
                return {
                    "statut": "non_disponible",
                    "resultat": None,
                    "hypotheses": hypotheses,
                    "arbre_name": candidat.name,
                    "detail": "question complémentaire sans défaut possible",
                }
            depart = None
            continue

        if isinstance(res, Resultat):
            return {
                "statut": "ok",
                "resultat": res,
                "hypotheses": hypotheses,
                "arbre_name": candidat.name,
                "detail": "",
            }

        return {
            "statut": "non_disponible",
            "resultat": None,
            "hypotheses": hypotheses,
            "arbre_name": candidat.name,
            "detail": f"retour de parcours inattendu : {type(res).__name__}",
        }

    return {
        "statut": "non_disponible",
        "resultat": None,
        "hypotheses": hypotheses,
        "arbre_name": "",
        "detail": "boucle de cascade (garde-fou)",
    }


# ─── Construction des lignes de la matrice ──────────────────────────────────

# Lignes « types de fertilisants » façon catalogue (avec la distinction
# type II digestat / hors digestat que les PAR exploitent par expression).
# Chaque ligne fige un fertilisant représentatif pour peupler les champs
# fins (categorie_fertilisant / sous_fertilisant) lus par les arbres.
LIGNES_FERTILISANTS = [
    {
        "id": "type_0",
        "label": "Type 0",
        "contexte": {
            "type_fertilisant": "type_0",
            "categorie_fertilisant": "composts",
            "sous_fertilisant": "compost_dechets_verts_jeunes_ligneux",
        },
    },
    {
        "id": "type_Ia",
        "label": "Type Ia",
        "contexte": {
            "type_fertilisant": "type_Ia",
            "categorie_fertilisant": "fumiers",
            "sous_fertilisant": "fumier_compact_non_susceptible_ecoulement",
        },
    },
    {
        "id": "type_Ib",
        "label": "Type Ib",
        "contexte": {
            "type_fertilisant": "type_Ib",
            "categorie_fertilisant": "fumiers",
            "sous_fertilisant": "fumier_mou_susceptible_ecoulement",
        },
    },
    {
        "id": "type_II",
        "label": "Type II (sauf digestat)",
        "contexte": {
            "type_fertilisant": "type_II",
            "categorie_fertilisant": "lisiers",
            "sous_fertilisant": "dejection_sans_litiere",
        },
    },
    {
        "id": "type_II_digestat",
        "label": "Type II : digestat de méthanisation",
        "contexte": {
            "type_fertilisant": "type_II",
            "categorie_fertilisant": "digestats",
            "sous_fertilisant": "digestat_brut_methanisation",
        },
    },
    {
        "id": "type_III",
        "label": "Type III",
        "contexte": {
            "type_fertilisant": "type_III",
            "categorie_fertilisant": "engrais_mineral",
            "sous_fertilisant": "engrais_azote_mineral",
        },
    },
]


def lignes_cultures() -> list[dict]:
    """Une ligne par branche culturale active, avec une Culture représentative
    (de préférence sans champs_prefill, pour rester sur le cas générique) qui
    fournit occupation_sol / sous_culture_form aux expressions des PAR."""
    from envergo.nitrates.models import BrancheCulturale, Culture

    cultures_par_branche: dict[str, list[Culture]] = {}
    for c in Culture.objects.select_related("branche_culturale"):
        cultures_par_branche.setdefault(c.branche_culturale.identifiant, []).append(c)

    lignes = []
    for branche in BrancheCulturale.objects.all():
        cultures = cultures_par_branche.get(branche.identifiant) or []
        if not cultures:
            continue
        representative = next(
            (c for c in cultures if not c.champs_prefill), cultures[0]
        )
        contexte = {
            "occupation_sol": representative.occupation_sol,
            "sous_culture": branche.identifiant,
            "sous_culture_form": representative.identifiant,
        }
        contexte.update(representative.champs_prefill or {})
        lignes.append(
            {
                "id": branche.identifiant,
                "label": branche.libelle_court.capitalize(),
                "contexte": contexte,
                "occupation_sol": representative.occupation_sol,
            }
        )
    return lignes


def catalog_synthetique(region_code: str, en_zar: bool) -> dict:
    """Catalog minimal pour select_active_trees, sans géo. Pour la ZAR, on
    résout un zar_zone_id représentatif depuis l'arbre ZAR actif de la
    région (première zone de sa couche d'activation)."""
    catalog = {"region_code": region_code}
    if en_zar:
        from envergo.nitrates.models import DecisionTree

        tree = (
            DecisionTree.objects.filter(
                status=DecisionTree.STATUS_ACTIVE,
                scope=DecisionTree.SCOPE_ZAR,
                region_code=region_code,
            )
            .select_related("activation_map")
            .first()
        )
        if tree and tree.activation_map_id:
            zone = tree.activation_map.zones.only("id").first()
            if zone:
                catalog["zar_zone_id"] = zone.id
    return catalog


def _est_plafond(code: str, referentiel_pc: dict) -> bool:
    data = referentiel_pc.get(str(code))
    return bool(data.get("plafond")) if isinstance(data, dict) else False


def construire_matrice(
    *,
    region_code: str,
    en_zar: bool,
    en_zone_vulnerable: bool,
    axe: str,  # "fertilisant" (culture figée) | "culture" (fertilisant figé)
    valeur_figee: str,
    referentiels: dict,
    dates: dict[str, str] | None = None,
) -> list[Cellule]:
    """Construit les cellules de la matrice : une par ligne de l'axe variable.

    `axe='fertilisant'` : `valeur_figee` = id de branche culturale, lignes =
    types de fertilisants. `axe='culture'` : `valeur_figee` = id de ligne
    fertilisant, lignes = branches culturales.
    """
    dates = {k: v for k, v in (dates or {}).items() if v}
    candidats = select_active_trees(catalog_synthetique(region_code, en_zar))
    referentiel_pc = referentiels.get("codes_prescription", {})
    cultures = lignes_cultures()

    if axe == "fertilisant":
        fixe = next((c for c in cultures if c["id"] == valeur_figee), None)
        lignes = [
            {"id": f["id"], "label": f["label"], "contexte": f["contexte"]}
            for f in LIGNES_FERTILISANTS
        ]
    else:
        fixe = next((f for f in LIGNES_FERTILISANTS if f["id"] == valeur_figee), None)
        lignes = [
            {"id": c["id"], "label": c["label"], "contexte": c["contexte"]}
            for c in cultures
        ]
    if fixe is None:
        return []

    cellules = []
    for ligne in lignes:
        contexte = {"en_zone_vulnerable": en_zone_vulnerable}
        contexte.update(fixe["contexte"])
        contexte.update(ligne["contexte"])
        contexte.update(dates)
        issue = evaluer_combinaison(candidats, contexte)
        cellule = Cellule(
            ligne_id=ligne["id"],
            ligne_label=ligne["label"],
            statut=issue["statut"],
            hypotheses=issue["hypotheses"],
            arbre_name=issue["arbre_name"],
            detail=issue["detail"],
        )
        res = issue["resultat"]
        if res is not None:
            cellule.regle = res
            cellule.chemin = res.chemin
            cellule.is_calculatrice = res.type == "calculatrice"
            if res.a_completer:
                cellule.statut = "non_disponible"
                cellule.detail = "règle à compléter (stub brouillon)"
            else:
                # Résolution géo des PC (même logique que le simulateur : la
                # rédaction affichée dépend du territoire, pas de l'arbre).
                codes = resoudre_codes_prescription(
                    list(res.codes_prescription),
                    referentiel_pc,
                    region_code=region_code,
                    en_zar=en_zar,
                )
                tous_plafonds = bool(codes) and all(
                    _est_plafond(c, referentiel_pc) for c in codes
                )
                for code in codes:
                    data = referentiel_pc.get(code) or {}
                    entry = {"code": code, **(data if isinstance(data, dict) else {})}
                    if _est_plafond(code, referentiel_pc):
                        cellule.plafonds.append(entry)
                    else:
                        cellule.pcs.append(entry)

                periodes = list(res.periodes or [])
                # Même synthèse que le calendrier statique : une règle ASC /
                # plafonnement SANS période = sous condition toute l'année.
                if not periodes and res.type in (
                    "autorisation_sous_condition",
                    "plafonnement",
                ):
                    periodes = [{"du": "01/07", "au": "30/06", "regime": res.type}]
                if not periodes and res.type == "interdiction":
                    periodes = [{"du": "01/07", "au": "30/06"}]
                regimes = compute_regime_par_jour(
                    res.type, periodes, dates, tous_plafonds=tous_plafonds
                )
                if res.type == "non_applicable":
                    cellule.statut = "non_applicable"
                cellule.segments = segments_depuis_regimes(regimes)
                cellule.has_orange = any(
                    s["couleur"] == "orange" for s in cellule.segments
                )
        cellules.append(cellule)
    return cellules
