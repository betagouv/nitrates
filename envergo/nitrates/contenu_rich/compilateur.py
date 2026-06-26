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


def _rich(valeur) -> str:
    """Rend un texte riche -> HTML inline SAFE (carte #136, gras inline).

    `valeur` peut être :
      - une string : texte plat, simplement échappé (cas historique) ;
      - une liste de segments {texte, gras} : chaque segment est échappé puis,
        si `gras` est vrai, enveloppé dans <strong>. Le gras est donc porté par
        une marque STRUCTURÉE, jamais par du HTML saisi -> impossible d'injecter
        autre chose que <strong> (sécurité conservée : on échappe tout, on
        ré-introduit nous-mêmes la seule balise autorisée).
    Renvoie une chaîne safe (mark_safe).
    """
    if valeur is None:
        return ""
    if isinstance(valeur, str):
        return format_html("{0}", valeur)
    if isinstance(valeur, list):
        morceaux = []
        for seg in valeur:
            if isinstance(seg, str):
                morceaux.append(format_html("{0}", seg))
                continue
            if not isinstance(seg, dict):
                continue
            txt = seg.get("texte", "") or ""
            if seg.get("gras"):
                morceaux.append(format_html("<strong>{0}</strong>", txt))
            else:
                morceaux.append(format_html("{0}", txt))
        return mark_safe("".join(morceaux))
    # Type inattendu -> on le rend en texte échappé par sécurité.
    return format_html("{0}", str(valeur))


def _texte(data: dict) -> str:
    """Texte riche d'un bloc (clé `texte`), tolérant aux clés vides.

    Passe par `_rich` : accepte string OU liste de segments {texte, gras}."""
    return _rich((data or {}).get("texte", ""))


def _niveau(n: int) -> int:
    return max(NIVEAU_TITRE_BASE, min(NIVEAU_TITRE_MAX, n))


def _compile_titre_principal(data, niveau, ctx):
    n = _niveau(niveau)
    return format_html('<h{0} class="fr-h{0}">{1}</h{0}>', n, _texte(data))


def _compile_titre_paragraphe(data, niveau, ctx):
    # Sous-titre de section. Coralie (commentaires Notion #136) demande
    # explicitement un H6 DSFR (Marianne 20px/700) pour ces sous-titres
    # « Le principe », « Les conditions… », « La dose maximale »… On rend donc
    # un vrai <h6 class="fr-h6"> (titre sémantique, meilleure a11y que le <p>
    # gras précédent) plutôt qu'un paragraphe en gras.
    return format_html('<h6 class="fr-h6">{0}</h6>', _texte(data))


def _compile_paragraphe(data, niveau, ctx):
    return format_html("<p>{0}</p>", _texte(data))


def _compile_items_liste(items) -> str:
    """Rend récursivement une liste d'items (puces + sous-puces)."""
    morceaux = []
    for item in items or []:
        texte = _rich((item or {}).get("texte", ""))
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
    # blocs, rendus à un niveau de titre incrémenté. id unique via le compteur
    # ET le préfixe de zone (cf. compile_dsfr) : plusieurs blocs riches peuvent
    # coexister sur la même page, et `aria-controls`/`id` doivent rester uniques
    # à l'échelle du document, pas seulement du bloc (carte #157).
    ctx["accordion_seq"] += 1
    accordion_id = f"{ctx['id_prefix']}-accordion-{ctx['accordion_seq']}"
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


# Pas de spacing négatif ni d'indentation délirante : on borne le niveau.
_INDENT_MAX = 6
_INDENT_REM = 1.5  # marge gauche par niveau d'indentation


def _indenter(html: str, data: dict) -> str:
    """Enveloppe le HTML d'un bloc dans une marge gauche si `data.indent` > 0
    (carte #136). Indentation « façon Notion » : chaque niveau décale de 1.5rem.
    Wrapper <div> neutre (n'altère pas le sens DSFR du bloc enveloppé)."""
    try:
        indent = int((data or {}).get("indent") or 0)
    except (TypeError, ValueError):
        indent = 0
    indent = max(0, min(_INDENT_MAX, indent))
    if indent == 0:
        return html
    marge = indent * _INDENT_REM
    return format_html(
        '<div style="margin-left:{}rem">{}</div>', marge, mark_safe(html)
    )


def _compile_blocs(blocs, niveau, ctx) -> str:
    morceaux = []
    for bloc in blocs or []:
        if not isinstance(bloc, dict):
            continue
        compiler = _COMPILERS.get(bloc.get("type"))
        if compiler is None:
            continue
        data = bloc.get("data") or {}
        html = compiler(data, niveau, ctx)
        morceaux.append(_indenter(html, data))
    return mark_safe("".join(morceaux))


def compile_dsfr(
    blocs, niveau_base: int = NIVEAU_TITRE_BASE, id_prefix: str = "contenu-rich"
) -> str:
    """Compile une liste de blocs en HTML DSFR (chaîne safe).

    `blocs` : liste de blocs typés (cf. spec §4). Accepte aussi l'enveloppe
    {"schema": N, "blocs": [...]} pour tolérance.
    `niveau_base` : niveau de titre HTML de départ (3 = <h3>, sous les
    prescriptions). Incrémenté dans les foldables.
    `id_prefix` : préfixe des `id`/`aria-controls` des accordéons. DOIT être
    distinct pour chaque zone de contenu riche rendue sur une même page, sinon
    deux blocs génèrent des `id` identiques (`...-accordion-1`) et un bouton
    pilote le mauvais dépliant (carte #157). Les appelants (templatetags
    `contenu_rich` / `compile_blocs`) dérivent un préfixe stable par zone.

    Renvoie une chaîne marquée safe. Le texte des blocs est échappé.
    """
    if isinstance(blocs, dict):
        blocs = blocs.get("blocs", [])
    ctx = {"accordion_seq": 0, "id_prefix": id_prefix or "contenu-rich"}
    contenu = _compile_blocs(blocs, niveau_base, ctx)
    if not contenu:
        return contenu
    # Conteneur `.contenu-rich` : porte le style de rendu (retrait des listes,
    # espacement des titres) défini dans calendrier.css, chargé partout où le
    # contenu rich s'affiche (résultat, simulateur, preview). Garantit un rendu
    # public identique à l'éditeur admin (#136).
    return format_html('<div class="contenu-rich">{0}</div>', mark_safe(contenu))


__all__ = ["compile_dsfr", "NIVEAU_TITRE_BASE"]
