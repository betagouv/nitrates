"""Tags visuels et filtres pour le viewer admin.

Decouple du HTML : ces fonctions sont testables en pur Python.

Les filtres rapides reposent sur 2 fonctions :
  - matches(tag_filtre, kind, data) : ce noeud/regle correspond au tag ?
  - subtree_matches(tag_filtre, noeud) : un descendant correspond ?
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Tag:
    label: str
    css: str
    icon: str = ""


# ─── Definitions ─────────────────────────────────────────────────────────────

_FORMULAIRE_NIVEAUX = {
    "culture": Tag("culture", "tag-form-culture", "📋"),
    "sous_culture": Tag("sous-culture", "tag-form-sous-culture", "📋"),
    "type_fertilisant": Tag("fertilisant", "tag-form-fertilisant", "📋"),
    "complement": Tag("complement", "tag-form-complement", "📋"),
}

_REGLE_TYPES = {
    "interdiction": Tag("interdiction", "tag-regle-interdiction", "🚫"),
    "autorisation_sous_condition": Tag("autorisation", "tag-regle-autorisation", "✅"),
    "plafonnement": Tag("plafonnement", "tag-regle-plafonnement", "📊"),
    "libre": Tag("libre", "tag-regle-libre", "🟢"),
    "non_applicable": Tag("non applicable", "tag-regle-non-applicable", "⚪"),
    "calculatrice": Tag("calculatrice", "tag-regle-calculatrice", "🧮"),
    "mixte": Tag("mixte", "tag-regle-mixte", "🔀"),
}

_CATALOGUE_TAG = Tag("catalogue", "tag-catalogue", "🌍")
_RENVOI_TAG = Tag("renvoi", "tag-renvoi", "↪️")
_A_COMPLETER_TAG = Tag("a completer", "tag-a-completer", "⚠️")


# Liste des filtres rapides exposes en barre d'outils (ordre = ordre d'affichage).
# Chaque filtre est (cle GET, Tag affiche pour le bouton).
QUICK_FILTERS: list[tuple[str, Tag]] = [
    ("culture", _FORMULAIRE_NIVEAUX["culture"]),
    ("sous_culture", _FORMULAIRE_NIVEAUX["sous_culture"]),
    ("type_fertilisant", _FORMULAIRE_NIVEAUX["type_fertilisant"]),
    ("complement", _FORMULAIRE_NIVEAUX["complement"]),
    ("catalogue", _CATALOGUE_TAG),
    ("interdiction", _REGLE_TYPES["interdiction"]),
    ("autorisation", _REGLE_TYPES["autorisation_sous_condition"]),
    ("plafonnement", _REGLE_TYPES["plafonnement"]),
    ("libre", _REGLE_TYPES["libre"]),
    ("non_applicable", _REGLE_TYPES["non_applicable"]),
    ("calculatrice", _REGLE_TYPES["calculatrice"]),
    ("renvoi", _RENVOI_TAG),
    ("a_completer", _A_COMPLETER_TAG),
]
QUICK_FILTER_KEYS = {k for k, _ in QUICK_FILTERS}


def get_tags(entry_kind: str, data: dict) -> list[Tag]:
    tags: list[Tag] = []
    if entry_kind == "noeud":
        tn = data.get("type_noeud")
        if tn == "catalogue":
            tags.append(_CATALOGUE_TAG)
            src = data.get("source")
            if src:
                tags.append(Tag(src, f"tag-source-{src}"))
        elif tn == "formulaire":
            niveau = data.get("niveau")
            if niveau and niveau in _FORMULAIRE_NIVEAUX:
                tags.append(_FORMULAIRE_NIVEAUX[niveau])
            else:
                tags.append(Tag("formulaire", "tag-formulaire", "📋"))
    elif entry_kind == "regle":
        rtype = data.get("type")
        if rtype and rtype in _REGLE_TYPES:
            tags.append(_REGLE_TYPES[rtype])
        elif data.get("a_completer"):
            tags.append(Tag("regle", "tag-regle"))
    elif entry_kind == "renvoi_vers":
        tags.append(_RENVOI_TAG)

    if isinstance(data, dict) and data.get("a_completer"):
        tags.append(_A_COMPLETER_TAG)
    return tags


# ─── Predicats : un noeud / regle correspond a un filtre ? ───────────────────


def matches_filter(filtre: str, kind: str, data: dict) -> bool:
    """Le noeud/regle/renvoi correspond-il directement au filtre ?"""
    if not filtre or not isinstance(data, dict):
        return False
    if filtre == "a_completer":
        return data.get("a_completer") is True
    if filtre == "catalogue":
        return kind == "noeud" and data.get("type_noeud") == "catalogue"
    if filtre in {"culture", "sous_culture", "type_fertilisant", "complement"}:
        return (
            kind == "noeud"
            and data.get("type_noeud") == "formulaire"
            and data.get("niveau") == filtre
        )
    if filtre == "interdiction":
        return kind == "regle" and data.get("type") == "interdiction"
    if filtre == "autorisation":
        return kind == "regle" and data.get("type") == "autorisation_sous_condition"
    if filtre == "plafonnement":
        return kind == "regle" and data.get("type") == "plafonnement"
    if filtre == "libre":
        return kind == "regle" and data.get("type") == "libre"
    if filtre == "non_applicable":
        return kind == "regle" and data.get("type") == "non_applicable"
    if filtre == "calculatrice":
        return kind == "regle" and data.get("type") == "calculatrice"
    if filtre == "renvoi":
        return kind == "renvoi_vers"
    return False


def subtree_matches(filtre: str, noeud: dict) -> bool:
    """Au moins un noeud / regle / renvoi du sous-arbre (inclus) match
    le filtre ? Sert a decider si on doit ouvrir ce noeud + ancetres."""
    if not isinstance(noeud, dict):
        return False
    if matches_filter(filtre, "noeud", noeud):
        return True
    for branche in noeud.get("branches") or []:
        if not isinstance(branche, dict):
            continue
        if "regle" in branche and isinstance(branche["regle"], dict):
            if matches_filter(filtre, "regle", branche["regle"]):
                return True
        if "renvoi_vers" in branche:
            if matches_filter(filtre, "renvoi_vers", branche):
                return True
        if "noeud" in branche and subtree_matches(filtre, branche["noeud"]):
            return True
    return False


# ─── Compatibilite : helpers nommes utilises ailleurs ────────────────────────


def has_a_completer(noeud: dict) -> bool:
    return subtree_matches("a_completer", noeud)


def subtree_has_calculatrice(noeud: dict) -> bool:
    return subtree_matches("calculatrice", noeud)


def regime_tag(regime: str | None) -> Tag | None:
    """Tag visuel pour un `regime` de periode. Reutilise les memes couleurs
    que les tags de regle (cf. _REGLE_TYPES) pour coherence visuelle :
    interdiction = rouge, autorisation_sous_condition = orange, etc."""
    if not regime:
        return None
    return _REGLE_TYPES.get(regime)
