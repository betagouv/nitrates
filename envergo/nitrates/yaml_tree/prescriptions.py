"""Sélection des codes de prescription applicables (#147).

Une feuille d'arbre référence des codes de prescription de BASE (pc1,
pc12…). La rédaction réellement affichée dépend de la géo de la parcelle,
pas de l'arbre qui a matché : les arbres PAR/ZAR sont des overrides
partiels, et une feuille PAN atteinte par fallback de cascade en Grand
Est doit quand même afficher la version Grand Est de la PC.

Le résolveur applique deux passes sur la liste de codes d'une feuille :

  1. FUSION : quand tous les composants d'une PC fusion (rédaction
     combinée écrite par les juristes, ex pc1_pc12 = pc1 + pc12) sont
     présents, la fusion remplace ses composants — à la position du
     premier composant. Plus grande fusion d'abord, ordre alphabétique à
     taille égale (déterminisme).
  2. DÉCLINAISON : chaque code restant est remplacé par sa déclinaison
     géographique applicable de poids maximal (zar 20 > region 10 >
     national 1, cf. SCOPE_WEIGHT), fallback sur le code lui-même.

Même modèle de résolution que la sélection d'arbres (loader_db
.select_active_trees), mais purement en mémoire : le résolveur travaille
sur le dict `codes_prescription` du référentiel déjà caché process-local
(cf. loader.load_referentiels), zéro requête SQL.
"""

from envergo.nitrates.constants import SCOPE_NATIONAL, SCOPE_WEIGHT, SCOPE_ZAR


def resoudre_codes_prescription(
    codes: list[str],
    codes_referentiel: dict,
    region_code: str | None = None,
    en_zar: bool = False,
) -> list[str]:
    """Codes de prescription à AFFICHER pour une feuille + une géo données.

    `codes` : les codes portés par la feuille (post-surcharges d'arbre).
    `codes_referentiel` : dict {identifiant: data} du référentiel (cf.
    loader._build_referentiels, clés `scope` / `region_code` /
    `variante_de` / `composants_fusion` posées hors défaut).
    `region_code` : code région INSEE de la parcelle (ex "44"), None/"" si
    inconnu. `en_zar` : la parcelle est en zone d'action renforcée.

    Ordre d'origine préservé, doublons retirés. Un code inconnu du
    référentiel est conservé tel quel (le template a son propre fallback
    d'affichage) mais ne peut ni fusionner ni se décliner.
    """
    dedup = []
    for code in codes or []:
        if code and code not in dedup:
            dedup.append(code)
    fusionnes = _appliquer_fusions(dedup, codes_referentiel)

    resolus = []
    for code in fusionnes:
        decline = _decliner(code, codes_referentiel, region_code, en_zar)
        if decline not in resolus:
            resolus.append(decline)
    return resolus


def _entry(codes_referentiel: dict, code: str) -> dict:
    data = codes_referentiel.get(code)
    return data if isinstance(data, dict) else {}


def _appliquer_fusions(codes: list[str], codes_referentiel: dict) -> list[str]:
    """Remplace chaque combinaison complète de composants par sa PC fusion."""
    fusions = []
    for ident, data in codes_referentiel.items():
        if not isinstance(data, dict):
            continue
        composants = data.get("composants_fusion") or []
        # Seules les fusions de BASE portent des composants ; leurs
        # déclinaisons géographiques passent par la passe 2 (variante_de).
        if composants and not data.get("variante_de"):
            fusions.append((frozenset(composants), ident))
    fusions.sort(key=lambda f: (-len(f[0]), f[1]))

    restants = list(codes)
    for composants, fusion_id in fusions:
        if not composants <= set(restants):
            continue
        nouveaux = []
        pose = False
        for code in restants:
            if code in composants:
                if not pose:
                    nouveaux.append(fusion_id)
                    pose = True
            else:
                nouveaux.append(code)
        restants = nouveaux
    return restants


def _applicable(data: dict, region_code: str | None, en_zar: bool) -> bool:
    """True si la zone d'application de `data` couvre la géo donnée."""
    scope = data.get("scope", SCOPE_NATIONAL)
    if scope == SCOPE_NATIONAL:
        return True
    if not region_code or data.get("region_code") != region_code:
        return False
    if scope == SCOPE_ZAR:
        return en_zar
    return True


def _decliner(
    code: str,
    codes_referentiel: dict,
    region_code: str | None,
    en_zar: bool,
) -> str:
    """Déclinaison applicable de poids max pour `code`, fallback le code.

    Le code référencé par la feuille est TOUJOURS candidat (fallback),
    même hors de sa zone déclarée : une PC régionale autonome (sans base
    nationale, ex pc_ge) référencée directement par une feuille d'un
    arbre régional doit s'afficher là où cette feuille matche.
    """
    meilleur = code
    poids = SCOPE_WEIGHT.get(
        _entry(codes_referentiel, code).get("scope", SCOPE_NATIONAL), 1
    )
    for ident, data in codes_referentiel.items():
        if not isinstance(data, dict) or data.get("variante_de") != code:
            continue
        if not _applicable(data, region_code, en_zar):
            continue
        poids_variante = SCOPE_WEIGHT.get(data.get("scope", SCOPE_NATIONAL), 1)
        # Strictement supérieur : à poids égal (impossible par contrainte
        # DB, mais robuste), on garde le premier trouvé / le code de base.
        if poids_variante > poids:
            meilleur, poids = ident, poids_variante
    return meilleur
