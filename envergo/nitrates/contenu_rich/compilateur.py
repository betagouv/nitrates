"""Compilateur `blocs JSON -> HTML DSFR` (carte #131).

Fonction pure : on prend la liste de blocs typés (la source unique stockée
en DB, cf. `ContenuRichDSFR`) et on produit le HTML DSFR-compliant. Toute la
**forme** (classes DSFR, couleurs, niveaux de titre) vit ICI ; le contenu
saisi par le juriste ne porte que du **texte et de la structure**.

Sécurité : le texte des blocs est traité comme du TEXTE PUR et systématiquement
échappé (`format_html` / `escape`). Le juriste ne peut donc PAS injecter de
HTML/JS — seules les balises produites par ce compilateur existent dans la
sortie. C'est plus strict (et plus simple) qu'un sanitizer type bleach qui
autoriserait un sous-ensemble de balises : ici on n'autorise AUCUNE balise
saisie. Si un jour on veut de l'inline (gras/italique), on passera par des
marques structurées (ex. {"texte": "...", "gras": true}), jamais par du HTML
brut dans le champ texte.

Types de blocs supportés (ensemble fini, cf. spec §3) :
  titre_principal, titre_paragraphe, paragraphe, liste (multi-niveaux),
  foldable (récursif, fr-accordion), citation (fr-callout).
"""

from django.utils.html import format_html
from django.utils.safestring import mark_safe

# Niveau de titre HTML de base pour `titre_principal`. Les règles permanentes
# s'insèrent SOUS les prescriptions du panneau (déjà en h3) -> on démarre les
# titres principaux de contenu en h3, et on descend (h4...) dans les foldables.
NIVEAU_TITRE_BASE = 3
NIVEAU_TITRE_MAX = 6  # <h6> est le plus profond en HTML

# Compteur d'id pour les accordéons (aria-controls doit être unique dans la
# page). On le passe en paramètre mutable pour rester sans état global.


def _texte(data: dict) -> str:
    """Récupère le texte d'un bloc, tolérant aux clés vides."""
    return (data or {}).get("texte", "") or ""


def _niveau(n: int) -> int:
    return max(NIVEAU_TITRE_BASE, min(NIVEAU_TITRE_MAX, n))


def _compile_titre_principal(data, niveau, ctx):
    n = _niveau(niveau)
    return format_html('<h{0} class="fr-h{0}">{1}</h{0}>', n, _texte(data))


def _compile_titre_paragraphe(data, niveau, ctx):
    # Sous-titre de section : gras, pas un vrai niveau de titre du document
    # (évite de casser la hiérarchie a11y). DSFR : texte mis en avant en gras.
    return format_html('<p class="fr-text--bold">{0}</p>', _texte(data))


def _compile_paragraphe(data, niveau, ctx):
    return format_html("<p>{0}</p>", _texte(data))


def _compile_items_liste(items) -> str:
    """Rend récursivement une liste d'items (puces + sous-puces)."""
    morceaux = []
    for item in items or []:
        texte = (item or {}).get("texte", "") or ""
        enfants = (item or {}).get("enfants") or []
        if enfants:
            morceaux.append(
                format_html(
                    "<li>{0}{1}</li>",
                    texte,
                    mark_safe(_compile_liste_ul(enfants)),
                )
            )
        else:
            morceaux.append(format_html("<li>{0}</li>", texte))
    return mark_safe("".join(morceaux))


def _compile_liste_ul(items) -> str:
    return format_html("<ul>{0}</ul>", _compile_items_liste(items))


def _compile_liste(data, niveau, ctx):
    items = (data or {}).get("items") or []
    # La 1re liste porte fr-mb-0 (cohérent avec le hardcode d'origine) ; les
    # sous-listes héritent du style DSFR par défaut.
    return format_html('<ul class="fr-mb-0">{0}</ul>', _compile_items_liste(items))


def _compile_citation(data, niveau, ctx):
    # Encadré à trait vertical gauche : fr-callout DSFR (callout = encadré
    # d'information avec barre latérale). Porte la mise en avant d'une formule
    # ou d'un point clé (ex. "Surface ÷ 20").
    return format_html(
        '<div class="fr-callout"><p class="fr-callout__text">{0}</p></div>',
        _texte(data),
    )


def _compile_foldable(data, niveau, ctx):
    # Section dépliable DSFR (fr-accordion), titre colorisé. Contient d'autres
    # blocs, rendus à un niveau de titre incrémenté. id unique via le compteur.
    ctx["accordion_seq"] += 1
    accordion_id = f"contenu-rich-accordion-{ctx['accordion_seq']}"
    titre = (data or {}).get("titre", "") or ""
    blocs_enfants = (data or {}).get("blocs") or []
    corps = _compile_blocs(blocs_enfants, niveau + 1, ctx)
    return format_html(
        '<section class="fr-accordion">'
        '<h{niv} class="fr-accordion__title">'
        '<button type="button" class="fr-accordion__btn" '
        'aria-expanded="false" aria-controls="{id}">{titre}</button>'
        "</h{niv}>"
        '<div class="fr-collapse" id="{id}">{corps}</div>'
        "</section>",
        niv=_niveau(niveau),
        id=accordion_id,
        titre=titre,
        corps=corps,
    )


# Table de dispatch type -> fonction de rendu. Tout type inconnu est ignoré
# silencieusement (robustesse : un JSON futur avec un type non géré ne crashe
# pas le rendu public ; le bloc est juste omis).
_COMPILERS = {
    "titre_principal": _compile_titre_principal,
    "titre_paragraphe": _compile_titre_paragraphe,
    "paragraphe": _compile_paragraphe,
    "liste": _compile_liste,
    "foldable": _compile_foldable,
    "citation": _compile_citation,
}


def _compile_blocs(blocs, niveau, ctx) -> str:
    morceaux = []
    for bloc in blocs or []:
        if not isinstance(bloc, dict):
            continue
        compiler = _COMPILERS.get(bloc.get("type"))
        if compiler is None:
            continue
        morceaux.append(compiler(bloc.get("data") or {}, niveau, ctx))
    return mark_safe("".join(morceaux))


def compile_dsfr(blocs, niveau_base: int = NIVEAU_TITRE_BASE) -> str:
    """Compile une liste de blocs en HTML DSFR (chaîne safe).

    `blocs` : liste de blocs typés (cf. spec §4). Accepte aussi l'enveloppe
    {"schema": N, "blocs": [...]} pour tolérance.
    `niveau_base` : niveau de titre HTML de départ (3 = <h3>, sous les
    prescriptions). Incrémenté dans les foldables.

    Renvoie une chaîne marquée safe. Le texte des blocs est échappé.
    """
    if isinstance(blocs, dict):
        blocs = blocs.get("blocs", [])
    ctx = {"accordion_seq": 0}
    contenu = _compile_blocs(blocs, niveau_base, ctx)
    # On enveloppe les foldables éventuels dans un groupe DSFR si présents ;
    # sinon le contenu est rendu tel quel. Le groupe accordéon DSFR attend
    # fr-accordions-group autour des <section class="fr-accordion">. Pour
    # rester simple et robuste au mélange (paragraphes + foldables), on ne
    # force pas le wrapper ici : l'intégration template fournit le conteneur.
    return contenu


__all__ = ["compile_dsfr", "NIVEAU_TITRE_BASE"]
