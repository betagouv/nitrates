"""Endpoints htmx d'edition inline d'un draft (etape 5c).

Tous les endpoints :
  - sont protegees par staff_member_required
  - exigent que le tree cible soit en statut DRAFT
  - exigent que l'utilisateur detienne le lock (sinon refus)
  - retournent des fragments HTML (pas des pages completes) destines a
    etre injectes par htmx dans la page courante via hx-target / hx-swap.

URL pattern : `/admin/nitrates/arbre-decision/<tree_pk>/edit/...`
Le path d'un noeud / branche est passe en query string ?path=a/b/c
(separateur slash) parce que les ids peuvent contenir des `/` (peu
probable mais on est safe).
"""

from __future__ import annotations

import re

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.utils.html import escape
from django.utils.text import slugify
from django.views import View

from envergo.nitrates.models import DecisionTree, DecisionTreeRevision
from envergo.nitrates.yaml_admin import editor
from envergo.nitrates.yaml_admin.catalogue_refs import CATALOGUE_RESOLVERS, get_resolver
from envergo.nitrates.yaml_admin.forms import (
    BrancheForm,
    NoeudFormulaireForm,
    RegleForm,
)
from envergo.nitrates.yaml_admin.grammar import (
    CATALOGUE_SOURCES_UI,
    SOURCE_EXPRESSION,
    FieldError,
    collect_champs_by_niveau,
    get_allowed_child_kinds,
)
from envergo.nitrates.yaml_admin.tags import get_tags
from envergo.nitrates.yaml_tree.expression import valider_expression


def _evenements_phenologiques() -> list[dict]:
    """Liste des evenements phenologiques depuis referentiels.yaml, pour
    proposer en datalist dans les inputs du/au des periodes. Permet
    d'eviter les typos (cf. brunissement_soies vs brunissement_des_soies)."""
    from envergo.nitrates.yaml_tree.loader import load_referentiels

    ref = load_referentiels()
    out = []
    for slug, data in (ref.get("evenements_phenologiques") or {}).items():
        out.append(
            {
                "slug": slug,
                "libelle": (data or {}).get("libelle_public") or slug,
            }
        )
    return out


def _regle_referentiel_choices() -> dict:
    """Choices fermees pour les champs canoniques d'une regle.

    - code_prescription : alimente depuis referentiels.yaml::codes_prescription.
      Affiche `pcN — mots_cles`, tooltip = texte_court.
    - note : alimente depuis referentiels.yaml::notes.
      Affiche `note_N — libelle_court`, tooltip = condition_declenchement.

    Une entree vide est toujours acceptee : toutes les regles n'ont pas
    un code de prescription ni une note (cas frequent).
    """
    try:
        from envergo.nitrates.yaml_tree.loader import load_referentiels

        ref = load_referentiels() or {}
    except Exception:
        return {"code_prescription": [], "note": []}

    codes_pc = []
    for slug, data in (ref.get("codes_prescription") or {}).items():
        data = data or {}
        codes_pc.append(
            {
                "value": slug,
                "libelle": data.get("mots_cles") or slug,
                "description": (data.get("texte_court") or "").strip(),
            }
        )

    notes = []
    for slug, data in (ref.get("notes") or {}).items():
        data = data or {}
        notes.append(
            {
                "value": slug,
                "libelle": data.get("libelle_court") or slug,
                "description": (data.get("condition_declenchement") or "").strip(),
            }
        )

    return {"code_prescription": codes_pc, "note": notes}


def _parse_path(raw: str | None) -> tuple[str, ...]:
    """Convertit `?path=n_root/q_culture` en tuple ('n_root', 'q_culture').
    Vide ou None -> tuple vide (=racine).
    """
    if not raw:
        return ()
    return tuple(p for p in raw.split("/") if p)


def _parse_valeur(raw):
    """Les valeurs de branches en YAML peuvent etre str, bool ou int.
    En query string elles arrivent en str. On reconstruit le type :
    `True`/`False` -> bool, sinon str (les ints sont rares et finissent
    aussi en str -- on accepte les deux ; le compare dans get_branche_at
    matchera le str si la valeur YAML est elle-meme un str).
    """
    if raw is None:
        return None
    # Tolere les deux casses : `True`/`False` (rendu Django d'un bool) et
    # `true`/`false` (saisie utilisateur, valeur de branche YAML booleenne).
    if raw in ("True", "true"):
        return True
    if raw in ("False", "false"):
        return False
    return raw


def _render_banner_oob(request, tree) -> str:
    """Re-rendu du bandeau d'edition en mode hx-swap-oob.

    Permet au bouton '↩ Annuler' (et au bloc historique) de refleter les
    revisions a jour sans full reload. Sinon le bandeau garde l'etat
    initial du chargement de page : si on est entre en edition sans
    revisions, '↩ Annuler' restait disabled meme apres une modif.

    IMPORTANT : on doit reproduire ICI tout le contexte que `YamlTreeView`
    passe au template `_edit_banner.html`, sinon le rerender perd des
    variables conditionnelles (#87 : `can_activate_this_tree` manquant
    -> branche else -> bouton 'Sauvegarder et publier' disparait apres
    chaque modif inline).

    Appele dans chaque vue d'edition inline qui modifie l'arbre.
    """
    from envergo.nitrates.permissions import can_activate_tree
    from envergo.nitrates.views_admin_yaml import _edited_origin_name

    banner_html = render(
        request,
        "nitrates_admin/yaml_tree/_edit_banner.html",
        {
            "tree": tree,
            "edited_origin_name": _edited_origin_name(tree, request.user),
            "can_activate_this_tree": can_activate_tree(request.user, tree),
            "recent_revisions": list(tree.revisions.order_by("-created_at")[:5]),
        },
    ).content.decode("utf-8")
    return banner_html.replace(
        '<div class="yaml-admin__edit-banner" id="yaml-admin-edit-banner">',
        '<div class="yaml-admin__edit-banner" id="yaml-admin-edit-banner"'
        ' hx-swap-oob="outerHTML">',
        1,
    )


def _render_partial_node_response(
    request, tree, parent_path: tuple[str, ...], message: str
) -> HttpResponse:
    """Renvoie le `<li>` du noeud parent re-rendu, avec headers htmx
    pour cibler le `<li>` existant du DOM.

    Cette reponse evite un full reload : le sous-arbre du parent est
    remis a jour en place, le scroll et le fold du reste de la page
    ne bougent pas.
    """
    from envergo.nitrates.yaml_admin.tags import QUICK_FILTERS
    from envergo.nitrates.yaml_tree import load_tree_admin

    arbre = load_tree_admin(tree)
    parent_node = editor.get_node_at(arbre, parent_path)
    if parent_node is None:
        # Fallback : full refresh si on ne retrouve pas le parent.
        return _refresh_response(request, message)

    # Le path du parent dans la representation du template.
    if parent_path:
        ancestors_str = "/".join(parent_path[:-1])
        parent_path_str = "/".join(parent_path)
    else:
        ancestors_str = ""
        parent_path_str = ""

    # On veut que le parent soit deplie (l'utilisateur vient de modifier
    # son contenu, on lui montre le resultat). On ouvre aussi tous ses
    # ancetres directs.
    open_paths: set[str] = set()
    if parent_path_str:
        open_paths.add(parent_path_str)
        # ancetres : "a", "a/b", ..., parent_path
        segs = parent_path_str.split("/")
        for i in range(1, len(segs)):
            open_paths.add("/".join(segs[:i]))
    # On peut etre conservateur et garder ouvert tout ce qu'il y avait
    # avant, mais le LocalStorage cote client gere deja ca au premier load.
    # Ici on s'assure juste que le parent reste deplie.

    rendered = render(
        request,
        "nitrates_admin/yaml_tree/_noeud.html",
        {
            "tree": tree,
            "noeud": parent_node,
            "ancestors_path": ancestors_str,
            "depth": len(parent_path) - 1 if parent_path else 0,
            "is_editing": True,
            "open_paths": open_paths,
            "expand": [],
            "expand_deep": [],
            "querystring_base": "",
            "quick_filters": QUICK_FILTERS,
        },
    ).content.decode("utf-8")

    # Toast inline via hx-swap-oob : htmx injecte ce fragment dans
    # `#yaml-admin-toast-zone` (defini dans base.html) en plus du swap
    # principal. Plus fiable que HX-Trigger qui ne se declenche pas
    # toujours apres un swap retargete.
    if message:
        import time

        toast_id = f"toast-{int(time.time() * 1000)}"
        toast_html = (
            f'<div hx-swap-oob="afterbegin:#yaml-admin-toast-zone">'
            f'<div class="yaml-admin__toast" id="{toast_id}">'
            f"{escape(message)}</div>"
            f"</div>"
        )
        rendered = rendered + toast_html

    rendered = rendered + _render_banner_oob(request, tree)

    response = HttpResponse(rendered)
    response["HX-Retarget"] = f"#node-{slugify(parent_path_str)}"
    response["HX-Reswap"] = "outerHTML"
    return response


def _refresh_response(request, message: str) -> HttpResponse:
    """Reponse htmx qui force un rechargement complet de la page courante.

    Le message est passe via Django messages framework -- il sera
    affiche en toaster sur la page rechargee. Le scroll est restaure
    par le JS de base.html (sessionStorage).

    On utilise HX-Refresh:true qui force un vrai reload navigateur. C'est
    plus brutal que HX-Redirect mais garantit qu'on voit l'arbre apres
    annulation/restauration -- sinon le HTML cote client reste sur l'etat
    pre-mutation.
    """
    if message:
        messages.info(request, message)
    response = HttpResponse(f"<div class='yaml-tree__add-ok'>{escape(message)}</div>")
    response["HX-Refresh"] = "true"
    return response


# Suggestions par niveau pour les champs canoniques d'un noeud formulaire.
# Le `champ` (slug technique) doit etre exactement celui-la car le parser
# de la moulinette s'en sert pour mapper a un input utilisateur.
# NB pour `culture` le champ canonique dans l'arbre national est
# `occupation_sol` (pas `culture`) -- la racine de la classification.
_NIVEAU_SUGGESTIONS = {
    "culture": {
        "champ": "occupation_sol",
        "texte_suggere": "Quelle est la culture en place ?",
    },
    "sous_culture": {
        "champ": "sous_culture",
        "texte_suggere": "Quelle culture utilisez-vous ?",
    },
    "type_fertilisant": {
        "champ": "type_fertilisant",
        "texte_suggere": "Quel type de fertilisant est utilisé ?",
    },
    "complement": {
        "champ": "",
        "texte_suggere": "",
    },
}


def _champ_from_niveau(niveau: str) -> str:
    """Champ technique canonique pour un niveau formulaire."""
    return _NIVEAU_SUGGESTIONS.get(niveau or "", {}).get("champ", "") or ""


def _check_editable(tree: DecisionTree, user) -> str | None:
    """Retourne un message d'erreur si l'utilisateur n'a pas le droit
    d'editer ce tree. None sinon."""
    if tree.status != DecisionTree.STATUS_DRAFT:
        return "L'édition n'est possible que sur un draft."
    # External observator : ne peut editer que ses propres drafts.
    from envergo.nitrates.permissions import is_external_observator

    if is_external_observator(user) and tree.created_by_id != user.pk:
        return (
            "Ce brouillon ne vous appartient pas. "
            "Vous pouvez le cloner pour en faire votre propre brouillon."
        )
    if tree.is_locked_by_other(user):
        return f"Édition verrouillée par {tree.locked_by.email if tree.locked_by else 'un autre utilisateur'}."
    # Refresh le lock (timestamp)
    tree.acquire_lock(user)
    return None


@method_decorator(staff_member_required, name="dispatch")
class EditNodeView(View):
    """GET : renvoie le fragment formulaire pour editer un noeud.
    POST : applique la modification + renvoie la ligne mise a jour.
    """

    def get(self, request, tree_pk):
        tree = get_object_or_404(DecisionTree, pk=tree_pk)
        err = _check_editable(tree, request.user)
        if err:
            return HttpResponseForbidden(err)
        path = _parse_path(request.GET.get("path"))
        node = editor.get_node_at(tree.contenu, path)
        if node is None:
            return HttpResponseForbidden("Nœud introuvable.")
        return render(
            request,
            "nitrates_admin/yaml_tree/forms/_node_form.html",
            {
                "tree": tree,
                "node": node,
                "path": path,
                "path_str": "/".join(path),
                "errors": [],
                "champs_by_niveau": collect_champs_by_niveau(tree.contenu),
                "catalogue_refs": CATALOGUE_RESOLVERS,
            },
        )

    def post(self, request, tree_pk):
        tree = get_object_or_404(DecisionTree, pk=tree_pk)
        err = _check_editable(tree, request.user)
        if err:
            return HttpResponseForbidden(err)
        path = _parse_path(request.GET.get("path") or request.POST.get("path"))
        node = editor.get_node_at(tree.contenu, path)
        if node is None:
            return HttpResponseForbidden("Nœud introuvable.")

        # Construit new_data depuis les champs POST (uniquement les
        # champs scalaires connus du noeud).
        new_data: dict = {"id": request.POST.get("id", "").strip() or node.get("id")}
        if node.get("type_noeud") == "formulaire":
            form = NoeudFormulaireForm(request.POST)
            if not form.is_valid():
                form_errors = [
                    FieldError(field, " / ".join(msgs))
                    for field, msgs in form.errors.items()
                ]
                return render(
                    request,
                    "nitrates_admin/yaml_tree/forms/_node_form.html",
                    {
                        "tree": tree,
                        "node": {**node, **dict(request.POST.items())},
                        "path": path,
                        "path_str": "/".join(path),
                        "errors": form_errors,
                        "champs_by_niveau": collect_champs_by_niveau(tree.contenu),
                        "catalogue_refs": CATALOGUE_RESOLVERS,
                    },
                    status=422,
                )
            cd = form.to_new_data()
            niveau = cd["niveau"] or node.get("niveau")
            new_data["id"] = cd["id"] or node.get("id")
            new_data["niveau"] = niveau
            new_data["texte"] = cd["texte"]
            # `champ` est derive du niveau pour les noeuds formulaire :
            # le parser de la moulinette compte sur cette correspondance
            # 1:1, et l'exposer en saisie libre permet de le casser
            # silencieusement. On accepte un override depuis le POST si
            # fourni (cas avance), sinon on derive automatiquement.
            new_data["champ"] = (
                cd["champ"] or _champ_from_niveau(niveau) or node.get("champ")
            )
            # `aide` est optionnel : on l'envoie toujours (meme vide)
            # pour que update_node retire la cle si l'utilisateur l'a
            # effacee (cf. convention "" = delete dans editor.update_node).
            new_data["aide"] = cd["aide"]
        elif node.get("type_noeud") == "catalogue":
            new_data["champ"] = request.POST.get("champ", "").strip()
            new_data["source"] = request.POST.get("source", "").strip() or node.get(
                "source"
            )
            # `reference` est optionnel : envoye toujours pour permettre
            # la suppression (cf. convention update_node).
            new_data["reference"] = request.POST.get("reference", "").strip()
        elif node.get("type_noeud") == "catalogue_parametre":
            # Catalogue en mode expression : on edite seulement le champ
            # logique. Le routage (expressions) se modifie branche par branche.
            new_data["champ"] = request.POST.get("champ", "").strip()

        result = editor.update_node(tree, path, new_data, request.user)
        if not result.ok:
            tree.refresh_from_db()
            node = editor.get_node_at(tree.contenu, path)
            return render(
                request,
                "nitrates_admin/yaml_tree/forms/_node_form.html",
                {
                    "tree": tree,
                    "node": {**node, **new_data},
                    "path": path,
                    "path_str": "/".join(path),
                    "errors": result.errors,
                    "champs_by_niveau": collect_champs_by_niveau(tree.contenu),
                },
                status=422,
            )
        # Succes : renvoie la ligne re-rendue (juste le summary visible
        # dans le row, sans les enfants -- htmx swap outerHTML sur le row).
        tree.refresh_from_db()
        # Si l'id a ete renomme, le path a change : on re-cible le noeud par son
        # NOUVEAU path (sinon get_node_at renvoie None -> 500 silencieux, pas de
        # swap, pas d'erreur -- bug renommage d'id).
        if new_data.get("id") and new_data["id"] != path[-1]:
            path = path[:-1] + (new_data["id"],)
        node = editor.get_node_at(tree.contenu, path)
        from envergo.nitrates.yaml_admin.preview import (
            build_preview_url,
            compute_simulator_params,
        )

        preview_link = build_preview_url(
            tree.pk, compute_simulator_params(tree.contenu, path)
        )
        body = render(
            request,
            "nitrates_admin/yaml_tree/forms/_node_row.html",
            {
                "tree": tree,
                "node": node,
                "path": path,
                "path_str": "/".join(path),
                "tags": get_tags("noeud", node),
                "preview_link": preview_link,
            },
        ).content.decode("utf-8")
        return HttpResponse(body + _render_banner_oob(request, tree))


def _regle_from_post(regle_orig: dict, post, form: RegleForm) -> dict:
    """Reconstruit un dict `regle` pour le re-render 422 du formulaire en
    cas d'echec de validation, en preservant les saisies utilisateur.

    Sans ca, le formulaire re-rendu efface tout : l'utilisateur perd ses
    modifications et doit tout ressaisir (bug critique reporte 2026-05-27).

    Strategie :
      - on part de `regle_orig` comme fallback,
      - on overlay les champs textuels directement depuis le POST (raw),
      - on overlay periodes + inputs_requis parses par le form
        (le form les parse meme en cas d'erreurs de validation, cf.
        _parse_periodes / _parse_inputs_requis qui ne raise pas).
    """
    out = {**regle_orig}
    # Champs scalaires : on prend tels quels depuis le POST (raw),
    # sans cleaning, sinon une checkbox decochee passerait inapercue.
    SCALAR_FIELDS = (
        "id",
        "type",
        "composant",
        "message",
        "texte",
        "texte_condition",
        "code_prescription",
        "source_juridique",
        "note",
        "plafonnement_associe",
        "plafond_azote_kg_n_ha",
    )
    for f in SCALAR_FIELDS:
        if f in post:
            val = (post.get(f) or "").strip()
            out[f] = val if val else None
    out["a_completer"] = bool(post.get("a_completer"))
    # periodes + inputs_requis : reparse via le form (deja fait dans clean()).
    out["periodes"] = form.periodes
    out["inputs_requis"] = form.inputs_requis
    _purger_champs_hors_nature(out, regle_orig)
    return out


# Champs qui n'ont de sens QUE pour une regle type=calculatrice (calendrier
# dynamique couvert). Le formulaire les masque en display:none quand on change
# la nature, mais display:none NE retire PAS l'input du DOM -> il reste poste,
# et `out = {**regle_orig}` conserve l'ancienne valeur. Sans purge explicite au
# save, ces champs survivent comme residus et fuient a l'affichage (ex: la bulle
# ⓘ texte_condition sur une regle passee en interdiction pure -- #218).
COMPOSANT_CALCULATRICE = "calendrier_dynamique_couvert"


def _purger_champs_hors_nature(out: dict, regle_orig: dict) -> None:
    """Nettoie in place les champs calculatrice orphelins quand la nature
    finale n'est plus calculatrice.

    - `composant` : purge SEULEMENT s'il vaut le composant calendrier couvert.
      Les autres composants (ex luzerne_post_coupe) sont legitimes pour type
      mixte -- on ne les touche pas.
    - `inputs_requis` : purge (dates de semis/destruction, inutiles hors calc).
    - `condition` / `masque` des periodes : purge (grammaire specifique calc).
    - `texte_condition` : purge UNIQUEMENT dans la transition calculatrice ->
      autre nature. Hors calculatrice, texte_condition est une justification
      metier LEGITIME (rendue en tooltip ⓘ sur interdiction/ASC/plafond, cf.
      periodes_par_section) : on ne l'efface pas sur la seule base du type,
      seulement s'il s'agit d'un residu herite d'une ancienne calculatrice.
    """
    if out.get("type") == "calculatrice":
        return  # nature calculatrice : tous ces champs sont a leur place.

    # Marqueur du residu = composant calendrier couvert sur nature non calc.
    # Les autres composants (ex luzerne_post_coupe/mixte) + leurs inputs_requis
    # sont legitimes -> on ne touche rien.
    if out.get("composant") != COMPOSANT_CALCULATRICE:
        # texte_condition peut quand meme etre un residu de calculatrice si
        # l'ancienne regle en etait une (transition calc -> autre nature).
        if (regle_orig or {}).get("type") == "calculatrice":
            out["texte_condition"] = None
        return

    out["composant"] = None
    out["inputs_requis"] = []
    for p in out.get("periodes") or []:
        p.pop("condition", None)
        p.pop("masque", None)

    # texte_condition : residu SEULEMENT si la regle etait calculatrice avant
    # (le texte datait du calendrier dynamique, pas d'une justification voulue).
    etait_calculatrice = (regle_orig or {}).get("type") == "calculatrice"
    if etait_calculatrice:
        out["texte_condition"] = None


@method_decorator(staff_member_required, name="dispatch")
class EditRegleView(View):
    """GET : formulaire pour editer une regle.
    POST : applique la modification + renvoie la ligne mise a jour.

    La regle est identifiee par le path de son noeud parent + la valeur
    de la branche dans laquelle elle est attachee :
        ?path=<parent_path>&valeur=<branche_valeur>
    """

    def get(self, request, tree_pk):
        tree = get_object_or_404(DecisionTree, pk=tree_pk)
        err = _check_editable(tree, request.user)
        if err:
            return HttpResponseForbidden(err)
        parent_path = _parse_path(request.GET.get("path"))
        valeur = _parse_valeur(request.GET.get("valeur"))
        branche = editor.get_branche_at(tree.contenu, parent_path, valeur)
        if branche is None or "regle" not in branche:
            return HttpResponseForbidden("Règle introuvable.")
        from envergo.nitrates.yaml_tree.parcours import normaliser_codes_prescription

        return render(
            request,
            "nitrates_admin/yaml_tree/forms/_regle_form.html",
            {
                "tree": tree,
                "regle": branche["regle"],
                # code_prescription du YAML peut etre scalaire OU liste : on
                # normalise en liste pour le widget multi-PC (sinon une PC
                # scalaire historique ne s'affiche pas -- regression compat).
                "codes_prescription_existants": normaliser_codes_prescription(
                    branche["regle"].get("code_prescription")
                ),
                "parent_path_str": "/".join(parent_path),
                "valeur": valeur,
                "errors": [],
                "evenements_phenologiques": _evenements_phenologiques(),
                "regle_choices": _regle_referentiel_choices(),
            },
        )

    def post(self, request, tree_pk):
        tree = get_object_or_404(DecisionTree, pk=tree_pk)
        err = _check_editable(tree, request.user)
        if err:
            return HttpResponseForbidden(err)
        parent_path = _parse_path(request.GET.get("path") or request.POST.get("path"))
        # Attention : bool False est falsy, donc on ne peut pas faire
        # `_parse_valeur(GET) or POST` (False bool serait perdu). On prefere
        # `valeur` du GET en priorite, sinon fallback POST.
        valeur_raw = request.GET.get("valeur")
        if valeur_raw is None:
            valeur_raw = request.POST.get("valeur")
        valeur = _parse_valeur(valeur_raw)
        branche = editor.get_branche_at(tree.contenu, parent_path, valeur)
        if branche is None or "regle" not in branche:
            return HttpResponseForbidden("Règle introuvable.")

        # Parsing + validation locale via RegleForm. La validation
        # sémantique (collisions d'id, etc.) reste dans editor.
        form = RegleForm(request.POST)
        if not form.is_valid():
            form_errors = [
                FieldError(field, " / ".join(msgs))
                for field, msgs in form.errors.items()
            ]
            # Bug fix : sur 422, on doit RE-AFFICHER les saisies de l'utilisateur,
            # pas la regle d'origine, sinon il perd tout. On overlay les valeurs
            # POST sur la regle originale.
            regle_display = _regle_from_post(branche["regle"], request.POST, form)
            return render(
                request,
                "nitrates_admin/yaml_tree/forms/_regle_form.html",
                {
                    "tree": tree,
                    "regle": regle_display,
                    "parent_path_str": "/".join(parent_path),
                    "valeur": valeur,
                    "errors": form_errors,
                    "evenements_phenologiques": _evenements_phenologiques(),
                    "regle_choices": _regle_referentiel_choices(),
                },
                status=422,
            )
        new_data = form.to_new_data()
        # #218 : purge du texte_condition RESIDUEL herite d'une ancienne
        # calculatrice. to_new_data() a deja purge les champs strictement
        # calculatrice (composant couvert, inputs_requis, condition/masque de
        # periode). texte_condition, lui, est une justification legitime hors
        # calculatrice -> on ne l'efface QUE dans la transition
        # calculatrice -> autre nature (ici on connait l'ancien type).
        etait_calculatrice = branche["regle"].get("type") == "calculatrice"
        if etait_calculatrice and new_data.get("type") != "calculatrice":
            new_data["texte_condition"] = None
        # Si la règle d'origine n'avait pas de périodes et que l'utilisateur
        # n'en a pas saisies, on retire `periodes` de new_data : pas la peine
        # de pousser une liste vide qui retirerait une clé déjà absente.
        if not new_data.get("periodes") and "periodes" not in branche["regle"]:
            new_data.pop("periodes", None)

        result = editor.update_regle(tree, parent_path, valeur, new_data, request.user)
        if not result.ok:
            tree.refresh_from_db()
            branche = editor.get_branche_at(tree.contenu, parent_path, valeur)
            current = {**branche["regle"], **new_data}
            return render(
                request,
                "nitrates_admin/yaml_tree/forms/_regle_form.html",
                {
                    "tree": tree,
                    "regle": current,
                    "parent_path_str": "/".join(parent_path),
                    "valeur": valeur,
                    "errors": result.errors,
                    "evenements_phenologiques": _evenements_phenologiques(),
                    "regle_choices": _regle_referentiel_choices(),
                },
                status=422,
            )
        # Succes : re-render la regle entiere (pas juste une ligne)
        tree.refresh_from_db()
        branche = editor.get_branche_at(tree.contenu, parent_path, valeur)
        body = render(
            request,
            "nitrates_admin/yaml_tree/forms/_regle_block.html",
            {
                "tree": tree,
                "arbre": tree.contenu,
                "regle": branche["regle"],
                "is_editing": True,
                "parent_path": "/".join(parent_path),
                "valeur": valeur,
            },
        ).content.decode("utf-8")
        return HttpResponse(body + _render_banner_oob(request, tree))


@method_decorator(staff_member_required, name="dispatch")
class CancelEditRegleView(View):
    """GET : annule l'edition d'une regle, renvoie le bloc en lecture."""

    def get(self, request, tree_pk):
        tree = get_object_or_404(DecisionTree, pk=tree_pk)
        parent_path = _parse_path(request.GET.get("path"))
        valeur = _parse_valeur(request.GET.get("valeur"))
        branche = editor.get_branche_at(tree.contenu, parent_path, valeur)
        if branche is None or "regle" not in branche:
            return HttpResponse(status=204)
        return render(
            request,
            "nitrates_admin/yaml_tree/forms/_regle_block.html",
            {
                "tree": tree,
                "arbre": tree.contenu,
                "regle": branche["regle"],
                "is_editing": True,
                "parent_path": "/".join(parent_path),
                "valeur": valeur,
            },
        )


@method_decorator(staff_member_required, name="dispatch")
class EditBrancheView(View):
    """GET / POST : edition de la valeur + libelle d'une branche.

    La branche est identifiee par son chemin parent + sa valeur courante :
        ?path=<parent_path>&valeur=<valeur>

    On ne touche pas a son contenu (noeud / regle / renvoi_vers) ici --
    c'est l'edition de la **branche elle-meme** (valeur scalaire + libelle).
    """

    def get(self, request, tree_pk):
        tree = get_object_or_404(DecisionTree, pk=tree_pk)
        err = _check_editable(tree, request.user)
        if err:
            return HttpResponseForbidden(err)
        parent_path = _parse_path(request.GET.get("path"))
        valeur = _parse_valeur(request.GET.get("valeur"))
        branche = editor.get_branche_at(tree.contenu, parent_path, valeur)
        if branche is None:
            return HttpResponseForbidden("Branche introuvable.")
        parent = editor.get_node_at(tree.contenu, parent_path)
        # Patch existant (remap code_prescription) : on l'expose en texte
        # 'src -> dst' (une ligne par remap) pour pre-remplir le textarea.
        patch_remap = (branche.get("patch") or {}).get("code_prescription") or {}
        patch_pc_text = "\n".join(f"{src} -> {dst}" for src, dst in patch_remap.items())
        return render(
            request,
            "nitrates_admin/yaml_tree/forms/_branche_form.html",
            {
                "tree": tree,
                "branche": branche,
                "parent_path_str": "/".join(parent_path),
                "valeur": valeur,
                "errors": [],
                "parent_type_noeud": (
                    parent.get("type_noeud") if isinstance(parent, dict) else None
                ),
                "renvoi_targets": (
                    _list_renvoi_targets(tree.contenu)
                    if "renvoi_vers" in branche
                    else []
                ),
                "valeur_choices": _branche_value_choices(tree.contenu, parent_path),
                "patch_pc_text": patch_pc_text,
            },
        )

    def post(self, request, tree_pk):
        tree = get_object_or_404(DecisionTree, pk=tree_pk)
        err = _check_editable(tree, request.user)
        if err:
            return HttpResponseForbidden(err)
        parent_path = _parse_path(request.GET.get("path") or request.POST.get("path"))
        valeur = _parse_valeur(request.GET.get("valeur") or request.POST.get("valeur"))
        branche = editor.get_branche_at(tree.contenu, parent_path, valeur)
        if branche is None:
            return HttpResponseForbidden("Branche introuvable.")

        form = BrancheForm(request.POST)
        if not form.is_valid():
            # Une seule erreur structurelle possible aujourd'hui : id de
            # renvoi non-slug. On rend le 1er message comme "renvoi".
            field, msgs = next(iter(form.errors.items()))
            return _render_branche_error(
                request,
                tree,
                branche,
                parent_path,
                valeur,
                field.replace("_new", ""),
                " / ".join(msgs),
            )
        cd = form.to_new_data()
        new_valeur_raw = cd["valeur_new_raw"]
        new_libelle = cd["libelle"]
        new_renvoi = cd["renvoi_vers_new"]

        # Conversion type-aware de la nouvelle valeur (preserve bool/int).
        if new_valeur_raw == "":
            return _render_branche_error(
                request,
                tree,
                branche,
                parent_path,
                valeur,
                "valeur",
                "La valeur est requise.",
            )
        # Sous un catalogue_parametre, la valeur de branche est une simple
        # ETIQUETTE (le routage se fait par l'expression Python) : on ne la
        # coerce JAMAIS en bool/int, sinon renommer "True" -> "oui" recoerce
        # "oui" en True et l'edition semble sans effet. Ailleurs, on preserve
        # le type de l'ancienne valeur (bool/int semantiques).
        parent = editor.get_node_at(tree.contenu, parent_path)
        est_catalogue_parametre = (
            isinstance(parent, dict)
            and parent.get("type_noeud") == "catalogue_parametre"
        )
        if est_catalogue_parametre:
            new_valeur = new_valeur_raw
        elif _est_catalogue_booleen(parent):
            # Gate catalogue dont le resolveur SIG renvoie un BOOLEEN
            # (valeurs_branches ("True","False")). La valeur de branche DOIT
            # etre un vrai booleen pour matcher au runtime -- independamment du
            # type de l'ancienne valeur. Sans ca, une ancienne valeur string
            # ('en_zge2', etc.) enfermerait toute correction en string et le
            # gate ne matcherait jamais (bug PAR Grand Est). Saisie non
            # booleenne ambigue -> on retombe sur la coercion generique.
            coerce = _coerce_valeur(new_valeur_raw, bool)
            new_valeur = (
                coerce
                if isinstance(coerce, bool)
                else _coerce_valeur(new_valeur_raw, type(valeur))
            )
        else:
            new_valeur = _coerce_valeur(new_valeur_raw, type(valeur))

        # Branche sous un catalogue_parametre : on valide et persiste son
        # expression de routage (#128).
        new_expression = None
        if est_catalogue_parametre:
            new_expression = request.POST.get("expression", "").strip()
            if not new_expression:
                return _render_branche_error(
                    request,
                    tree,
                    branche,
                    parent_path,
                    valeur,
                    "expression",
                    "L'expression est requise pour une branche de catalogue "
                    "paramétré.",
                )
            expr_err = valider_expression(new_expression)
            if expr_err:
                return _render_branche_error(
                    request,
                    tree,
                    branche,
                    parent_path,
                    valeur,
                    "expression",
                    expr_err,
                )

        # Si la nouvelle valeur != ancienne, on verifie qu'elle n'entre pas
        # en collision avec une autre branche du meme parent.
        if new_valeur != valeur:
            parent = editor.get_node_at(tree.contenu, parent_path)
            if parent is not None:
                for b in parent.get("branches") or []:
                    if isinstance(b, dict) and b.get("valeur") == new_valeur:
                        return _render_branche_error(
                            request,
                            tree,
                            branche,
                            parent_path,
                            valeur,
                            "valeur",
                            f"Une branche avec la valeur {new_valeur!r} existe deja.",
                        )

        # Application directe (mutation atomique sur la branche).
        from django.db import transaction

        from envergo.nitrates.models import DecisionTreeRevision

        with transaction.atomic():
            DecisionTreeRevision.record(
                tree,
                action=DecisionTreeRevision.ACTION_EDIT,
                user=request.user,
                target_path=f"{'/'.join(parent_path)}#{valeur}",
                description=f"Édition de la branche {valeur!r}",
            )
            branche["valeur"] = new_valeur
            if new_expression is not None:
                branche["expression"] = new_expression
            if new_libelle:
                branche["libelle"] = new_libelle
            elif "libelle" in branche:
                del branche["libelle"]
            # Si la branche est de type renvoi_vers, on applique la
            # nouvelle cible si fournie. On ne valide pas ici qu'elle
            # existe dans l'arbre -- le validateur deep le fera.
            if "renvoi_vers" in branche and new_renvoi:
                branche["renvoi_vers"] = new_renvoi
            # Patch optionnel sur renvoi_vers : remap de codes de prescription
            # sur la feuille atteinte. Saisi en texte, une regle par ligne au
            # format 'pcX -> pcY'. Plusieurs lignes = plusieurs remaps. Vide =
            # pas de patch (on retire la cle si elle existait).
            if "renvoi_vers" in branche:
                remap = _parse_patch_pc(request.POST.get("patch_pc", ""))
                if remap:
                    branche["patch"] = {"code_prescription": remap}
                else:
                    branche.pop("patch", None)
            tree.contenu_yaml_brut = editor._dump_yaml(tree.contenu)
            tree.save(update_fields=["contenu", "contenu_yaml_brut", "updated_at"])

        # Re-render le bloc branche en lecture
        body = render(
            request,
            "nitrates_admin/yaml_tree/forms/_branche_block.html",
            {
                "tree": tree,
                "branche": branche,
                "parent_path": "/".join(parent_path),
                "valeur": new_valeur,
                "is_editing": True,
            },
        ).content.decode("utf-8")
        return HttpResponse(body + _render_banner_oob(request, tree))


def _render_branche_error(request, tree, branche, parent_path, valeur, field, msg):
    from envergo.nitrates.yaml_admin.grammar import FieldError

    parent = editor.get_node_at(tree.contenu, parent_path)
    # Sur erreur, on re-affiche la saisie utilisateur (notamment l'expression)
    # plutot que la branche d'origine, pour ne pas la perdre.
    branche_display = dict(branche)
    if request.method == "POST" and "expression" in request.POST:
        branche_display["expression"] = request.POST.get("expression", "")
    return render(
        request,
        "nitrates_admin/yaml_tree/forms/_branche_form.html",
        {
            "tree": tree,
            "branche": branche_display,
            "parent_path_str": "/".join(parent_path),
            "valeur": valeur,
            "errors": [FieldError(field, msg)],
            "parent_type_noeud": (
                parent.get("type_noeud") if isinstance(parent, dict) else None
            ),
            "valeur_choices": _branche_value_choices(tree.contenu, parent_path),
        },
        status=422,
    )


# Mapping niveau d'un noeud formulaire -> cle de referentiels.yaml. Si un
# parent appartient a ce mapping, l'edition de ses branches enfants force la
# selection de la valeur dans un dropdown ferme (les slugs canoniques du
# referentiel). Source unique : envergo/nitrates/specs/referentiels.yaml.
# Le niveau `sous_culture` de l'arbre correspond a une BrancheCulturale (ORM),
# PAS a une Culture : on l'alimente depuis le modele BrancheCulturale (cf bug
# #142, le dropdown listait a tort les Cultures). Les autres niveaux mappent
# une cle de referentiels.yaml.
_NIVEAU_TO_REFERENTIEL_KEY = {
    "type_fertilisant": "types_fertilisants",
}


def _branche_value_choices(arbre: dict, parent_path: tuple[str, ...]) -> list[dict]:
    """Liste fermee des valeurs canoniques pour les branches enfants d'un
    parent formulaire.

    - niveau `sous_culture` -> les BrancheCulturale (ORM).
    - autres niveaux mappes -> une cle de referentiels.yaml.
    Retourne [] si le parent n'a pas de source -> le template retombe sur un
    <input> libre. Sinon [{value, libelle, description}] pour un <select> ferme.
    """
    parent = editor.get_node_at(arbre, parent_path)
    if not isinstance(parent, dict):
        return []
    if parent.get("type_noeud") != "formulaire":
        return []
    niveau = parent.get("niveau")

    if niveau == "sous_culture":
        try:
            from envergo.nitrates.models_referentiels import BrancheCulturale
        except Exception:
            return []
        return [
            {
                "value": b.identifiant,
                "libelle": b.libelle_court or b.identifiant,
                "description": b.description or "",
            }
            for b in BrancheCulturale.objects.all().order_by("ordre_affichage")
        ]

    ref_key = _NIVEAU_TO_REFERENTIEL_KEY.get(niveau)
    if not ref_key:
        return []
    try:
        from envergo.nitrates.yaml_tree.loader import load_referentiels

        ref = load_referentiels() or {}
    except Exception:
        return []
    items = ref.get(ref_key) or {}
    out = []
    for slug, data in items.items():
        data = data or {}
        out.append(
            {
                "value": slug,
                "libelle": data.get("libelle_court")
                or data.get("libelle_public")
                or data.get("libelle")
                or slug,
                "description": data.get("libelle_public")
                or data.get("description")
                or "",
            }
        )
    return out


def _normalise_pc(token: str) -> str:
    """Normalise un code de prescription saisi vers le slug canonique 'pcN'.

    Tolere : 'pc13', 'PC13', 'Pc 13', '13' -> 'pc13'. Les PC sont stockes en DB
    sous la forme 'pcN' ; sans cette normalisation un numero nu ('13') est
    rejete par le validateur ('code_prescription 13 inconnu')."""
    t = (token or "").strip().lower().replace(" ", "")
    if not t:
        return t
    if t.isdigit():
        return f"pc{t}"
    return t


def _parse_patch_pc(raw: str) -> dict:
    """Parse le textarea du patch : une regle par ligne 'pcX -> pcY'.
    Retourne {src: dst} avec les codes normalises en 'pcN' (cf. _normalise_pc :
    un numero nu '13' devient 'pc13'). Ignore les lignes vides / mal formees.
    Accepte '->' ou ':' comme separateur, espaces tolerants."""
    remap: dict = {}
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        sep = "->" if "->" in line else (":" if ":" in line else None)
        if not sep:
            continue
        src, _, dst = line.partition(sep)
        src, dst = _normalise_pc(src), _normalise_pc(dst)
        if src and dst:
            remap[src] = dst
    return remap


def _est_catalogue_booleen(parent) -> bool:
    """True si `parent` est un noeud catalogue (pas catalogue_parametre) dont
    la reference resout sur un BOOLEEN (resolveur a valeurs_branches
    ("True","False")).

    Sert a forcer la coercion booleenne des branches de ces gates (zonage
    SIG booleen : en_zone_vulnerable, zone_grand_est_1/2, zone_note_5,
    zone_montagne_d113_14...). On NE touche PAS aux formulaires (valeurs de
    reponse libres comme 'Non') ni aux catalogue_parametre (etiquettes)."""
    if not isinstance(parent, dict):
        return False
    if parent.get("type_noeud") != "catalogue":
        return False
    resolver = get_resolver(parent.get("reference") or "")
    if resolver is None:
        return False
    return tuple(resolver.valeurs_branches) == ("True", "False")


def _coerce_valeur(raw: str, target_type):
    """Convertit une saisie utilisateur vers le type cible (preserve bool/int)."""
    if target_type is bool:
        if raw.lower() in ("true", "1", "yes", "oui"):
            return True
        if raw.lower() in ("false", "0", "no", "non"):
            return False
        return raw  # fallback string si saisie ambigue
    if target_type is int:
        try:
            return int(raw)
        except ValueError:
            return raw
    return raw


@method_decorator(staff_member_required, name="dispatch")
class CancelEditBrancheView(View):
    """GET : annule l'edition d'une branche, renvoie le bloc en lecture."""

    def get(self, request, tree_pk):
        tree = get_object_or_404(DecisionTree, pk=tree_pk)
        parent_path = _parse_path(request.GET.get("path"))
        valeur = _parse_valeur(request.GET.get("valeur"))
        branche = editor.get_branche_at(tree.contenu, parent_path, valeur)
        if branche is None:
            return HttpResponse(status=204)
        return render(
            request,
            "nitrates_admin/yaml_tree/forms/_branche_block.html",
            {
                "tree": tree,
                "branche": branche,
                "parent_path": "/".join(parent_path),
                "valeur": valeur,
                "is_editing": True,
            },
        )


@method_decorator(staff_member_required, name="dispatch")
class AddChildView(View):
    """GET : renvoie le formulaire d'ajout d'une branche enfant a un noeud parent.
    POST : applique la creation (branche + son contenu) et renvoie un fragment
    de confirmation qui demande au navigateur de rafraichir la zone parente.

    Parametres :
      ?path=<parent_path>   : noeud parent dont on ajoute une branche.
      ?kind=<content_kind>  : optionnel ; type du contenu choisi par
                              l'utilisateur. Si absent : selectionne le
                              premier kind autorise.

    L'UX : on ouvre un formulaire qui combine :
      - la valeur de la branche (champ texte)
      - le libelle de la branche (optionnel)
      - un select du kind du contenu (filtre par get_allowed_child_kinds)
      - les champs propres au kind selectionne (id, niveau, texte, etc.)
    Le select declenche un re-render du formulaire au change (htmx) pour
    adapter les champs au kind choisi -- pas de JS custom.
    """

    def get(self, request, tree_pk):
        tree = get_object_or_404(DecisionTree, pk=tree_pk)
        err = _check_editable(tree, request.user)
        if err:
            return HttpResponseForbidden(err)
        parent_path = _parse_path(request.GET.get("path"))
        parent = editor.get_node_at(tree.contenu, parent_path)
        if parent is None:
            return HttpResponseForbidden("Nœud parent introuvable.")
        allowed = get_allowed_child_kinds(tree.contenu, parent_path)
        if not allowed:
            return HttpResponseForbidden("Aucun type d'enfant autorise sous ce noeud.")
        kind = request.GET.get("kind") or allowed[0]
        if kind not in allowed:
            kind = allowed[0]
        # Quand l'utilisateur change le `<select kind>`, htmx repostule
        # le GET avec hx-include des champs deja saisis. On les remet
        # dans form_data pour les preserver dans le re-render.
        form_data = {k: v for k, v in request.GET.items() if k not in ("path", "kind")}
        return render(
            request,
            "nitrates_admin/yaml_tree/forms/_add_form.html",
            {
                "tree": tree,
                "parent_path_str": "/".join(parent_path),
                "parent_niveau": (
                    parent.get("niveau") if isinstance(parent, dict) else None
                ),
                "parent_type_noeud": (
                    parent.get("type_noeud") if isinstance(parent, dict) else None
                ),
                "allowed_kinds": allowed,
                "selected_kind": kind,
                "errors": [],
                "form_data": form_data,
                "champs_by_niveau": collect_champs_by_niveau(tree.contenu),
                "catalogue_refs": CATALOGUE_RESOLVERS,
                "catalogue_sources_ui": CATALOGUE_SOURCES_UI,
                "renvoi_targets": _list_renvoi_targets(tree.contenu),
                "valeur_choices": _branche_value_choices(tree.contenu, parent_path),
                "regle_choices": _regle_referentiel_choices(),
            },
        )

    def post(self, request, tree_pk):
        tree = get_object_or_404(DecisionTree, pk=tree_pk)
        err = _check_editable(tree, request.user)
        if err:
            return HttpResponseForbidden(err)
        parent_path = _parse_path(request.GET.get("path") or request.POST.get("path"))
        parent = editor.get_node_at(tree.contenu, parent_path)
        if parent is None:
            return HttpResponseForbidden("Nœud parent introuvable.")
        allowed = get_allowed_child_kinds(tree.contenu, parent_path)
        kind = request.POST.get("kind", "").strip()
        if kind not in allowed:
            return _render_add_error(
                request,
                tree,
                parent_path,
                allowed,
                kind or (allowed[0] if allowed else ""),
                "kind",
                f"Type {kind!r} non autorise ici.",
            )

        # Valeur de branche
        valeur_raw = request.POST.get("valeur", "").strip()
        if valeur_raw == "":
            return _render_add_error(
                request,
                tree,
                parent_path,
                allowed,
                kind,
                "valeur",
                "La valeur de branche est requise.",
                form_data=request.POST,
            )
        # Coercion bool / int / str
        valeur = _coerce_branch_value(valeur_raw)
        # Refus si collision
        for b in parent.get("branches") or []:
            if isinstance(b, dict) and b.get("valeur") == valeur:
                return _render_add_error(
                    request,
                    tree,
                    parent_path,
                    allowed,
                    kind,
                    "valeur",
                    f"Une branche avec la valeur {valeur!r} existe deja.",
                    form_data=request.POST,
                )

        libelle = request.POST.get("libelle", "").strip()
        branche_data: dict = {"valeur": valeur}
        if libelle:
            branche_data["libelle"] = libelle

        # Branche sous un noeud catalogue_parametre (#128) : elle porte une
        # `expression` Python (routage) en plus de la valeur (etiquette +
        # tracabilite). On l'exige et on la valide avant de creer la branche.
        if parent.get("type_noeud") == "catalogue_parametre":
            expression = request.POST.get("expression", "").strip()
            if not expression:
                return _render_add_error(
                    request,
                    tree,
                    parent_path,
                    allowed,
                    kind,
                    "expression",
                    "L'expression est requise pour une branche de catalogue "
                    "paramétré.",
                    form_data=request.POST,
                )
            expr_err = valider_expression(expression)
            if expr_err:
                return _render_add_error(
                    request,
                    tree,
                    parent_path,
                    allowed,
                    kind,
                    "expression",
                    expr_err,
                    form_data=request.POST,
                )
            branche_data["expression"] = expression

        # 1) Cree la branche (squelette).
        res_branch = editor.add_branch(tree, parent_path, branche_data, request.user)
        if not res_branch.ok:
            return _render_add_errors(
                request,
                tree,
                parent_path,
                allowed,
                kind,
                res_branch.errors,
                form_data=request.POST,
            )

        # 2) Insere le contenu choisi.
        content = _build_content_data(
            kind, request.POST, parent_path, valeur, tree.contenu
        )
        res_content = editor.update_branch_content(
            tree, parent_path, valeur, kind, content, request.user
        )
        if not res_content.ok:
            # On a deja cree la branche : on annule en la supprimant pour
            # ne pas laisser un squelette vide.
            editor.delete_branch(tree, parent_path, valeur, request.user)
            return _render_add_errors(
                request,
                tree,
                parent_path,
                allowed,
                kind,
                res_content.errors,
                form_data=request.POST,
            )

        return _render_partial_node_response(
            request, tree, parent_path, f"Branche {valeur!r} ajoutée."
        )


def _coerce_branch_value(raw: str):
    """Convertit la saisie utilisateur d'une valeur de branche.
    Reconnait True/False/oui/non comme bool, les entiers comme int,
    sinon string."""
    lower = raw.lower()
    if lower in ("true", "oui"):
        return True
    if lower in ("false", "non"):
        return False
    try:
        return int(raw)
    except ValueError:
        return raw


def _build_content_data(
    kind: str,
    post,
    parent_path: tuple[str, ...] = (),
    valeur=None,
    arbre: dict | None = None,
) -> dict:
    """Reconstruit le dict du contenu (noeud, regle, renvoi_vers) depuis les
    champs POST. Les noms de champs sont prefixes par `c_` pour eviter les
    collisions avec valeur / kind / libelle.

    Si `c_id` est vide, on auto-genere un id base sur le contexte
    (parent_path + valeur), garantit unique dans l'arbre.
    """
    data: dict = {}
    if kind.startswith("noeud_formulaire_"):
        niveau = kind.removeprefix("noeud_formulaire_")
        data["id"] = post.get("c_id", "").strip() or _auto_id(
            "q", parent_path, valeur, arbre
        )
        data["type_noeud"] = "formulaire"
        data["niveau"] = niveau
        data["texte"] = post.get("c_texte", "").strip() or _NIVEAU_SUGGESTIONS.get(
            niveau, {}
        ).get("texte_suggere", "")
        # `champ` derive du niveau (cf. EditNodeView.post). On accepte un
        # override si l'utilisateur a ouvert "Options avancees" et l'a
        # explicitement saisi.
        data["champ"] = post.get("c_champ", "").strip() or _champ_from_niveau(niveau)
        aide = post.get("c_aide", "").strip()
        if aide:
            data["aide"] = aide
        data["branches"] = []
    elif kind == "noeud_catalogue":
        data["id"] = post.get("c_id", "").strip() or _auto_id(
            "n", parent_path, valeur, arbre
        )
        source = post.get("c_source", "").strip()
        if source == SOURCE_EXPRESSION:
            # Mode "expression" du catalogue : le branchement se fait par
            # expression Python sur chaque branche (#128). En interne c'est un
            # type_noeud catalogue_parametre, mais cote UI c'est juste un
            # catalogue dont la source est "expression". Pas de `source`
            # stockee (le type_noeud porte deja l'information).
            data["type_noeud"] = "catalogue_parametre"
            data["champ"] = post.get("c_champ", "").strip()
        else:
            data["type_noeud"] = "catalogue"
            data["champ"] = post.get("c_champ", "").strip()
            data["source"] = source
            ref = post.get("c_reference", "").strip()
            if ref:
                data["reference"] = ref
        data["branches"] = []
    elif kind == "regle":
        data["id"] = post.get("c_id", "").strip() or _auto_id(
            "r", parent_path, valeur, arbre
        )
        rtype = post.get("c_type", "").strip()
        if rtype:
            data["type"] = rtype
        if post.get("c_a_completer") in ("on", "true", "1"):
            data["a_completer"] = True
        # Periodes : POST contient c_periodes-{i}-du / c_periodes-{i}-au /
        # c_periodes-{i}-regime (optionnel).
        periodes = []
        i = 0
        while True:
            du = post.get(f"c_periodes-{i}-du", "").strip()
            au = post.get(f"c_periodes-{i}-au", "").strip()
            regime = post.get(f"c_periodes-{i}-regime", "").strip()
            if not du and not au and not regime:
                if i == 0:
                    break
                break
            if du or au or regime:
                p: dict = {}
                if du:
                    p["du"] = du
                if au:
                    p["au"] = au
                if regime:
                    p["regime"] = regime
                periodes.append(p)
            i += 1
        if periodes:
            data["periodes"] = periodes
        composant = post.get("c_composant", "").strip()
        if composant:
            data["composant"] = composant
        inputs_raw = post.get("c_inputs_requis", "").strip()
        if inputs_raw:
            data["inputs_requis"] = [
                x.strip() for x in inputs_raw.split(",") if x.strip()
            ]
        plafond = post.get("c_plafond_azote_kg_n_ha", "").strip()
        if plafond:
            try:
                data["plafond_azote_kg_n_ha"] = float(plafond)
            except ValueError:
                pass
        for k in (
            "note",
            "source_juridique",
            "code_prescription",
            "message",
            "texte",
            "texte_condition",
            "plafonnement_associe",
        ):
            v = post.get(f"c_{k}", "").strip()
            if v:
                data[k] = v
    elif kind == "renvoi_vers":
        data["renvoi_vers"] = post.get("c_renvoi_vers", "").strip()
    elif kind == "renvoi_arbre":
        data["renvoi_arbre"] = post.get("c_renvoi_arbre", "").strip()
    elif kind == "feuille_vide":
        data["feuille_vide"] = True
    return data


def _auto_id(prefix: str, parent_path: tuple[str, ...], valeur, arbre) -> str:
    """Genere automatiquement un id unique pour un nouveau noeud/regle.

    Strategie : `<prefix>_<short_parent>_<slug_valeur>`, avec suffixe
    numerique si collision.
    """
    from envergo.nitrates.yaml_admin.grammar import _collect_ids

    def _slug(s: str) -> str:
        import re
        import unicodedata

        s = unicodedata.normalize("NFD", str(s))
        s = "".join(c for c in s if unicodedata.category(c) != "Mn")
        s = re.sub(r"[^a-zA-Z0-9_]+", "_", s).strip("_").lower()
        return s or "x"

    # On prend les 1-2 derniers segments du parent_path comme contexte.
    parent_segments: list[str] = []
    if parent_path:
        # Strip le prefixe q_ / n_ / r_ pour aerer l'id
        for seg in parent_path[-2:]:
            seg = seg.lstrip("qnr").lstrip("_")
            parent_segments.append(_slug(seg))
    valeur_slug = _slug(valeur) if valeur is not None else ""
    candidate_parts = [p for p in (*parent_segments, valeur_slug) if p]
    base = f"{prefix}_{'_'.join(candidate_parts)}" if candidate_parts else f"{prefix}_x"

    existing = _collect_ids(arbre or {})
    if base not in existing:
        return base
    i = 2
    while f"{base}_{i}" in existing:
        i += 1
    return f"{base}_{i}"


def _render_add_error(
    request, tree, parent_path, allowed, kind, field, message, form_data=None
):
    return _render_add_errors(
        request,
        tree,
        parent_path,
        allowed,
        kind,
        [FieldError(field, message)],
        form_data=form_data,
    )


def _render_add_errors(
    request, tree, parent_path, allowed, kind, errors, form_data=None
):
    # Log au stdout pour faciliter le debug : Django renvoie 422 mais ne
    # logue pas les messages d'erreur, l'utilisateur ne voit que le
    # 422 dans le terminal/network.
    import sys

    print(
        f"[add-child 422] tree={tree.pk} path={'/'.join(parent_path)} "
        f"kind={kind!r} errors=[",
        ", ".join(f"{e.field!r}: {e.message!r}" for e in errors),
        "]",
        file=sys.stderr,
        flush=True,
    )
    parent = editor.get_node_at(tree.contenu, parent_path)
    return render(
        request,
        "nitrates_admin/yaml_tree/forms/_add_form.html",
        {
            "tree": tree,
            "parent_path_str": "/".join(parent_path),
            "parent_niveau": parent.get("niveau") if isinstance(parent, dict) else None,
            "allowed_kinds": allowed,
            "selected_kind": kind,
            "parent_type_noeud": (
                parent.get("type_noeud") if isinstance(parent, dict) else None
            ),
            "errors": errors,
            "form_data": form_data or {},
            "catalogue_refs": CATALOGUE_RESOLVERS,
            "catalogue_sources_ui": CATALOGUE_SOURCES_UI,
            "renvoi_targets": _list_renvoi_targets(tree.contenu),
            "valeur_choices": _branche_value_choices(tree.contenu, parent_path),
            "regle_choices": _regle_referentiel_choices(),
            "champs_by_niveau": collect_champs_by_niveau(tree.contenu),
        },
        status=422,
    )


@method_decorator(staff_member_required, name="dispatch")
class CancelAddChildView(View):
    """GET : ferme le formulaire d'ajout.

    Retourne le `<div id="add-zone-{path}"></div>` vide reinitialise plutot
    qu'une chaine vide. Sinon le swap outerHTML supprime carrement la zone
    cible, et le prochain clic sur le bouton `+` du noeud genere un
    htmx:targetError (le selecteur ne matche plus rien dans le DOM).
    """

    def get(self, request, tree_pk):
        path = request.GET.get("path", "")
        slug = slugify(path)
        return HttpResponse(f'<div id="add-zone-{slug}"></div>')


def _insert_parent_kinds(arbre: dict, node_path: tuple[str, ...]) -> list[str]:
    """Kinds proposables pour intercaler AU-DESSUS du noeud A (node_path).

    Le nouveau noeud N prend la place de A dans la branche du parent P : les
    kinds autorises sont donc ceux valides comme enfant de P. Seuls des noeuds
    (N doit avoir une branche pour heberger A)."""
    parent_path = node_path[:-1]
    return [
        k for k in get_allowed_child_kinds(arbre, parent_path) if k.startswith("noeud_")
    ]


def _render_insert_parent_form(
    request, tree, node_path, allowed, kind, errors=None, form_data=None
):
    node = editor.get_node_at(tree.contenu, node_path)
    return render(
        request,
        "nitrates_admin/yaml_tree/forms/_insert_parent_form.html",
        {
            "tree": tree,
            "node_path_str": "/".join(node_path),
            "node_id": node.get("id") if isinstance(node, dict) else "",
            "allowed_kinds": allowed,
            "selected_kind": kind,
            "errors": errors or [],
            "form_data": form_data or {},
            "champs_by_niveau": collect_champs_by_niveau(tree.contenu),
            "catalogue_refs": CATALOGUE_RESOLVERS,
            "catalogue_sources_ui": CATALOGUE_SOURCES_UI,
        },
        status=422 if errors else 200,
    )


@method_decorator(staff_member_required, name="dispatch")
class InsertParentView(View):
    """Intercale un nouveau noeud N juste AU-DESSUS d'un noeud A.

    Avant :  P --[X]--> A    Apres :  P --[X]--> N --[a_definir]--> A

    A (et tout son sous-arbre) descend sous une branche placeholder de N.
    Declenche depuis la barre d'actions du noeud A (icone ⤴) : `path` = A.

    GET  ?path=<node_path>[&kind=...] : formulaire.
    POST idem : applique l'intercalation.
    """

    def get(self, request, tree_pk):
        tree = get_object_or_404(DecisionTree, pk=tree_pk)
        err = _check_editable(tree, request.user)
        if err:
            return HttpResponseForbidden(err)
        node_path = _parse_path(request.GET.get("path"))
        if not node_path:
            return HttpResponseForbidden("La racine ne peut pas être intercalée.")
        node = editor.get_node_at(tree.contenu, node_path)
        if node is None:
            return HttpResponseForbidden("Nœud introuvable.")
        allowed = _insert_parent_kinds(tree.contenu, node_path)
        if not allowed:
            return HttpResponseForbidden("Aucun nœud intercalable ici.")
        kind = request.GET.get("kind") or allowed[0]
        if kind not in allowed:
            kind = allowed[0]
        form_data = {k: v for k, v in request.GET.items() if k not in ("path", "kind")}
        return _render_insert_parent_form(
            request, tree, node_path, allowed, kind, form_data=form_data
        )

    def post(self, request, tree_pk):
        tree = get_object_or_404(DecisionTree, pk=tree_pk)
        err = _check_editable(tree, request.user)
        if err:
            return HttpResponseForbidden(err)
        node_path = _parse_path(request.GET.get("path") or request.POST.get("path"))
        allowed = _insert_parent_kinds(tree.contenu, node_path)
        kind = request.POST.get("kind", "").strip()
        if kind not in allowed:
            return _render_insert_parent_form(
                request,
                tree,
                node_path,
                allowed,
                kind or (allowed[0] if allowed else ""),
                errors=[FieldError("kind", f"Type {kind!r} non intercalable ici.")],
                form_data=request.POST,
            )
        # Contenu du nouveau noeud (builder d'ajout). Le mutator lui greffe
        # l'unique branche placeholder vers A ; valeur d'auto-id neutre.
        content = _build_content_data(
            kind, request.POST, node_path, "intercale", tree.contenu
        )
        result = editor.insert_parent(tree, node_path, kind, content, request.user)
        if not result.ok:
            return _render_insert_parent_form(
                request,
                tree,
                node_path,
                allowed,
                kind,
                errors=result.errors,
                form_data=request.POST,
            )
        # Le sous-arbre re-render est celui du PARENT de A (c'est lui qui porte
        # desormais N a la place de A).
        return _render_partial_node_response(
            request, tree, node_path[:-1], "Nœud parent intercalé."
        )


@method_decorator(staff_member_required, name="dispatch")
class CancelInsertParentView(View):
    """GET : ferme le formulaire d'intercalation en vidant sa zone d'accueil.

    Meme principe que CancelAddChildView : on renvoie le <div> vide reinitialise
    (pas une chaine vide, sinon le swap outerHTML supprime la cible et le
    prochain clic sur ⤴ genere un htmx:targetError).
    """

    def get(self, request, tree_pk):
        path = request.GET.get("path", "")
        slug = slugify(path)
        return HttpResponse(f'<div id="insert-parent-zone-{slug}"></div>')


# Kinds de contenu FEUILLE (pas de noeud enfant) entre lesquels on peut basculer
# une branche feuille existante sans la supprimer/recreer.
_CHANGE_CONTENT_KINDS = ("regle", "renvoi_vers", "renvoi_arbre", "feuille_vide")


def _render_change_content_form(
    request, tree, parent_path, valeur, kind, errors=None, form_data=None
):
    zone_id = (
        f"change-content-zone-{slugify('/'.join(parent_path))}-{slugify(str(valeur))}"
    )
    return render(
        request,
        "nitrates_admin/yaml_tree/forms/_change_content_form.html",
        {
            "tree": tree,
            "parent_path_str": "/".join(parent_path),
            "valeur": valeur,
            "zone_id": zone_id,
            "allowed_kinds": list(_CHANGE_CONTENT_KINDS),
            "selected_kind": kind,
            "errors": errors or [],
            "form_data": form_data or {},
            "renvoi_targets": _list_renvoi_targets(tree.contenu),
        },
        status=422 if errors else 200,
    )


@method_decorator(staff_member_required, name="dispatch")
class ChangeBranchContentView(View):
    """Change le TYPE de contenu d'une branche feuille existante (renvoi_vers ->
    feuille_vide, regle -> renvoi_vers, etc.) sans la supprimer/recreer.

    Ne s'applique qu'aux branches feuilles (pas de noeud enfant) : changer le
    type d'une branche qui porte un sous-arbre n'a pas de sens (on perdrait le
    sous-arbre). `path` = noeud parent, `valeur` = branche.
    """

    def get(self, request, tree_pk):
        tree = get_object_or_404(DecisionTree, pk=tree_pk)
        err = _check_editable(tree, request.user)
        if err:
            return HttpResponseForbidden(err)
        parent_path = _parse_path(request.GET.get("path"))
        valeur = _parse_valeur(request.GET.get("valeur"))
        branche = editor.get_branche_at(tree.contenu, parent_path, valeur)
        if branche is None:
            return HttpResponseForbidden("Branche introuvable.")
        if isinstance(branche.get("noeud"), dict):
            return HttpResponseForbidden(
                "Cette branche porte un sous-arbre : changer son type le "
                "perdrait. Réservé aux branches feuilles."
            )
        # Kind courant (pour pre-selectionner le select).
        kind = request.GET.get("kind") or _kind_courant_branche(branche)
        if kind not in _CHANGE_CONTENT_KINDS:
            kind = _CHANGE_CONTENT_KINDS[0]
        form_data = {
            k: v for k, v in request.GET.items() if k not in ("path", "kind", "valeur")
        }
        return _render_change_content_form(
            request, tree, parent_path, valeur, kind, form_data=form_data
        )

    def post(self, request, tree_pk):
        tree = get_object_or_404(DecisionTree, pk=tree_pk)
        err = _check_editable(tree, request.user)
        if err:
            return HttpResponseForbidden(err)
        parent_path = _parse_path(request.GET.get("path") or request.POST.get("path"))
        valeur = _parse_valeur(request.GET.get("valeur") or request.POST.get("valeur"))
        kind = request.POST.get("kind", "").strip()
        if kind not in _CHANGE_CONTENT_KINDS:
            return _render_change_content_form(
                request,
                tree,
                parent_path,
                valeur,
                _CHANGE_CONTENT_KINDS[0],
                errors=[FieldError("kind", f"Type {kind!r} non autorisé ici.")],
                form_data=request.POST,
            )
        content = _build_content_data(
            kind, request.POST, parent_path, valeur, tree.contenu
        )
        result = editor.update_branch_content(
            tree, parent_path, valeur, kind, content, request.user
        )
        if not result.ok:
            return _render_change_content_form(
                request,
                tree,
                parent_path,
                valeur,
                kind,
                errors=result.errors,
                form_data=request.POST,
            )
        return _render_partial_node_response(
            request, tree, parent_path, f"Type de la branche {valeur!r} changé."
        )


def _kind_courant_branche(branche: dict) -> str:
    """Kind feuille courant d'une branche (pour pre-selectionner le select)."""
    for kind, key in (
        ("renvoi_vers", "renvoi_vers"),
        ("renvoi_arbre", "renvoi_arbre"),
        ("feuille_vide", "feuille_vide"),
        ("regle", "regle"),
    ):
        if key in branche:
            return kind
    return _CHANGE_CONTENT_KINDS[0]


@method_decorator(staff_member_required, name="dispatch")
class CancelChangeBranchContentView(View):
    """GET : ferme le form de changement de type (vide la zone d'accueil)."""

    def get(self, request, tree_pk):
        path = request.GET.get("path", "")
        valeur = request.GET.get("valeur", "")
        slug = f"{slugify(path)}-{slugify(valeur)}"
        return HttpResponse(f'<div id="change-content-zone-{slug}"></div>')


@method_decorator(staff_member_required, name="dispatch")
class DeleteBrancheView(View):
    """POST : supprime une branche entiere (et tout son contenu).

    ?path=<parent_path>&valeur=<valeur>
    """

    def post(self, request, tree_pk):
        tree = get_object_or_404(DecisionTree, pk=tree_pk)
        err = _check_editable(tree, request.user)
        if err:
            return HttpResponseForbidden(err)
        parent_path = _parse_path(request.GET.get("path"))
        valeur = _parse_valeur(request.GET.get("valeur"))
        result = editor.delete_branch(tree, parent_path, valeur, request.user)
        if not result.ok:
            return HttpResponseForbidden(
                "; ".join(e.message for e in result.errors) or "Suppression refusee."
            )
        return _render_partial_node_response(
            request, tree, parent_path, f"Branche {valeur!r} supprimée."
        )


@method_decorator(staff_member_required, name="dispatch")
class ReorderBranchesView(View):
    """POST : reordonne les branches d'un noeud parent.

    ?path=<parent_path>
    body : `order=val1,val2,val3,...` (valeurs des branches dans le
        nouvel ordre desire). Les valeurs `True`/`False` doivent etre
        envoyees telles quelles (strings) ; on les decode comme bool
        pour matcher la cle de stockage.
    """

    def post(self, request, tree_pk):
        tree = get_object_or_404(DecisionTree, pk=tree_pk)
        err = _check_editable(tree, request.user)
        if err:
            return HttpResponseForbidden(err)
        parent_path = _parse_path(request.GET.get("path"))
        order_raw = request.POST.get("order", "")
        if not order_raw:
            return HttpResponseForbidden("Aucun ordre fourni.")
        # Liste des valeurs : on garde les strings et on decode les bools
        # avec `_parse_valeur` (cf. _parse_valeur : "True" -> True, ...).
        ordered_valeurs = [_parse_valeur(v) for v in order_raw.split(",")]
        result = editor.reorder_branches(
            tree, parent_path, ordered_valeurs, request.user
        )
        if not result.ok:
            return HttpResponseForbidden(
                "; ".join(e.message for e in result.errors)
                or "Réordonnancement refusé.",
            )
        # Pas de re-render : le DOM est deja a jour cote front (SortableJS
        # a deja deplace les elements). On renvoie juste un 204 + le
        # banner OOB pour rafraichir l'historique de revisions.
        return HttpResponse(_render_banner_oob(request, tree))


@method_decorator(staff_member_required, name="dispatch")
class DeleteNodeView(View):
    """POST : supprime un noeud descendant (et son sous-arbre + la branche
    qui le porte). Ne peut pas supprimer la racine.

    ?path=<node_path>
    """

    def post(self, request, tree_pk):
        tree = get_object_or_404(DecisionTree, pk=tree_pk)
        err = _check_editable(tree, request.user)
        if err:
            return HttpResponseForbidden(err)
        path = _parse_path(request.GET.get("path"))
        result = editor.delete_node(tree, path, request.user)
        if not result.ok:
            return HttpResponseForbidden(
                "; ".join(e.message for e in result.errors) or "Suppression refusee."
            )
        # On swap le grand-parent : le noeud supprime + sa branche
        # disparaissent. Si on n'a pas de grand-parent (suppression d'un
        # enfant direct de la racine), on prend le parent.
        parent_path = path[:-1] if len(path) >= 2 else path[:-1]
        return _render_partial_node_response(
            request,
            tree,
            parent_path,
            f"Nœud {path[-1] if path else ''} supprimé.",
        )


@method_decorator(staff_member_required, name="dispatch")
class ConvertNodeView(View):
    """POST : convertit un nœud (question complémentaire ou catalogue) en
    catalogue_parametre, sur place, sans perdre les branches existantes
    (#128). Chaque branche reçoit une `expression` vide à remplir ensuite.

    ?path=<node_path>
    """

    def post(self, request, tree_pk):
        tree = get_object_or_404(DecisionTree, pk=tree_pk)
        err = _check_editable(tree, request.user)
        if err:
            return HttpResponseForbidden(err)
        path = _parse_path(request.GET.get("path"))
        result = editor.convert_node_to_catalogue_parametre(tree, path, request.user)
        if not result.ok:
            return HttpResponseForbidden(
                "; ".join(e.message for e in result.errors) or "Conversion refusée."
            )
        # La conversion renomme l'id (q_* -> n_*) : on re-render avec le NOUVEAU
        # path, sinon les actions htmx suivantes cibleraient l'ancien id
        # (introuvable -> 403, "ca sauvegarde pas"). result.new_id porte le
        # nouvel id quand un renommage a eu lieu.
        nouveau_path = path
        if result.new_id and path:
            nouveau_path = path[:-1] + (result.new_id,)
        return _render_partial_node_response(
            request,
            tree,
            nouveau_path,
            f"Nœud {nouveau_path[-1] if nouveau_path else ''} converti en "
            f"catalogue paramétré. Renseignez l'expression de chaque branche.",
        )


@method_decorator(staff_member_required, name="dispatch")
class ValidateTreeView(View):
    """POST : lance la validation deep d'un draft. Renvoie un panneau
    HTML avec la liste des erreurs, ou un message OK si l'arbre est
    valide. La validation ne modifie pas le draft."""

    def post(self, request, tree_pk):
        from envergo.nitrates.yaml_tree import load_tree_admin
        from envergo.nitrates.yaml_tree.validator import ValidationError, validate_arbre

        tree = get_object_or_404(DecisionTree, pk=tree_pk)
        if tree.status != DecisionTree.STATUS_DRAFT:
            return HttpResponseForbidden(
                "La validation deep n'est pertinente que sur un draft."
            )
        arbre = load_tree_admin(tree)
        try:
            validate_arbre(arbre, scope=tree.scope)
            errors: list[str] = []
        except ValidationError as e:
            errors = list(e.errors)
        return render(
            request,
            "nitrates_admin/yaml_tree/_validation_panel.html",
            {
                "tree": tree,
                "errors": [_humanize_error(arbre, e) for e in errors],
            },
        )


def _humanize_error(arbre: dict, raw_error: str) -> dict:
    """Transforme une erreur de validation en dict {label, message, raw, kind}.

    `label` : ID TECHNIQUE du noeud/regle/branche concerne (ex: 'r_colza',
    'q_fertilisant'), pour reperer direct dans l'editeur -- PAS un chemin
    metier (trop long/lent a lire, cf. retour Max 2026-06-17).
    `message` : la fin du message d'erreur, sans prefixe technique.
    `raw` : message original, montre au survol pour debug.
    `kind` : "structure" / "renvoi_vers" / "niveau" / "ids" / "date" / ...
    """
    import re

    # Erreur de structure (jsonschema) : "[structure] arbre/.../path : msg".
    # On extrait le dernier id technique du path (le plus proche de l'erreur).
    m = re.match(r"^\[structure\]\s*(?P<path>\S*)\s*:\s*(?P<msg>.*)$", raw_error)
    if m:
        return {
            "label": _dernier_id_technique(m.group("path")),
            "message": m.group("msg"),
            "raw": raw_error,
            "kind": "structure",
        }

    # Erreur renvoi_vers : "[renvoi_vers] 'r_xxx' (depuis branche valeur=X) ..."
    m = re.match(
        r"^\[renvoi_vers\]\s*'(?P<cible>[^']+)'\s*"
        r"\(depuis branche valeur=(?P<valeur>[^)]+)\)\s*(?P<msg>.*)$",
        raw_error,
    )
    if m:
        valeur = m.group("valeur").strip().strip("'\"")
        cible = m.group("cible")
        # ID technique du noeud qui PORTE la branche en erreur (pour la trouver
        # dans l'editeur), a defaut la valeur de branche.
        owner = _find_branch_owner_id(arbre, valeur, "renvoi_vers", cible)
        return {
            "label": owner or valeur,
            "message": f"renvoi vers '{cible}' inconnu",
            "raw": raw_error,
            "kind": "renvoi_vers",
        }

    # Erreur niveau : "[niveau] noeud 'q_xxx' : msg" -> id technique = q_xxx.
    m = re.match(
        r"^\[niveau\]\s*noeud\s*'(?P<nid>[^']+)'\s*:\s*(?P<msg>.*)$", raw_error
    )
    if m:
        return {
            "label": m.group("nid"),
            "message": m.group("msg"),
            "raw": raw_error,
            "kind": "niveau",
        }

    # Cas generique : on tente d'extraire un id technique entre quotes du
    # message (regle 'r_xxx', noeud 'q_xxx'...), sinon pas de label.
    m = re.match(r"^\[(?P<kind>\w+)\]\s*(?P<rest>.*)$", raw_error)
    if m:
        rest = m.group("rest")
        id_match = re.search(r"'([a-z][a-zA-Z0-9_]+)'", rest)
        return {
            "label": id_match.group(1) if id_match else "",
            "message": rest,
            "raw": raw_error,
            "kind": m.group("kind"),
        }
    return {"label": "", "message": raw_error, "raw": raw_error, "kind": ""}


def _dernier_id_technique(path: str) -> str:
    """Dernier segment ressemblant a un id technique (q_/n_/r_...) d'un path
    jsonschema 'arbre/noeud/branches/2/noeud/...'. Vide si rien."""
    if not path:
        return ""
    segs = [
        s for s in re.split(r"[/.]", path) if re.match(r"^[a-z]_?[a-zA-Z0-9_]*$", s)
    ]
    technique = [s for s in segs if "_" in s]
    return technique[-1] if technique else (segs[-1] if segs else "")


def _find_branch_owner_id(arbre: dict, valeur: str, key: str, value: str) -> str:
    """ID du noeud qui porte la branche {valeur, key:value}. Vide si introuvable."""
    racine = (arbre or {}).get("arbre", {}).get("noeud")
    if not racine:
        return ""
    return _walk_for_branch_owner(racine, valeur, key, value) or ""


def _walk_for_branch_owner(noeud, target_valeur, target_key, target_value):
    if not isinstance(noeud, dict):
        return None
    for branche in noeud.get("branches") or []:
        if not isinstance(branche, dict):
            continue
        if str(branche.get("valeur")) == str(target_valeur) and str(
            branche.get(target_key)
        ) == str(target_value):
            return noeud.get("id")
        res = _walk_for_branch_owner(
            branche.get("noeud"), target_valeur, target_key, target_value
        )
        if res is not None:
            return res
    return None


def _list_renvoi_targets(arbre: dict) -> list[dict]:
    """Liste tous les ids cibles potentiels pour un renvoi_vers, avec
    pour chacun son label metier (chemin) pour aider a choisir.

    Les cibles incluent :
      - regles dans l'arbre (avec leur chemin metier complet)
      - regles top-level dans plafonnements et regles_partagees
      - noeuds (renvoi vers un noeud entier est rare mais possible)

    Retourne une liste [{id, label, group}] triee par groupe puis label.
    """
    targets: list[dict] = []

    # Regles + noeuds dans l'arbre
    racine = (arbre or {}).get("arbre", {}).get("noeud")
    if racine:
        _collect_targets_in_node(racine, [], targets)

    # Regles top-level
    for top_key in ("plafonnements", "regles_partagees"):
        for entry in (arbre or {}).get(top_key) or []:
            regle = entry.get("regle") if isinstance(entry, dict) else None
            if isinstance(regle, dict) and regle.get("id"):
                # Petit label : le message ou l'id
                label = regle.get("message") or regle.get("id")
                targets.append(
                    {
                        "id": regle["id"],
                        "label": label,
                        "group": top_key,
                    }
                )

    # Tri : groupe (arbre d'abord), puis label
    targets.sort(key=lambda t: (t["group"], t["label"]))
    return targets


def _collect_targets_in_node(noeud, crumbs, out):
    """Construit la liste des cibles pour le select de renvoi.

    Le breadcrumb ne contient QUE les valeurs/libelles des branches
    traversees (les "reponses"), pas les textes des noeuds (les
    "questions"). C'est ce qui distingue les chemins ; les questions
    sont redondantes et rendent les options illisibles.

    Ex: "Oui > Culture principale > Colza > type_II > zone_note_5"
    au lieu de "en_zone_vulnerable > Oui > Est-ce que la culture est…"
    """
    if not isinstance(noeud, dict):
        return
    # On ajoute aussi les noeuds (utile pour renvoyer vers un sous-arbre).
    if noeud.get("id"):
        out.append(
            {
                "id": noeud["id"],
                "label": " > ".join(crumbs) if crumbs else noeud["id"],
                "group": "arbre",
            }
        )
    for branche in noeud.get("branches") or []:
        if not isinstance(branche, dict):
            continue
        b_label = branche.get("libelle") or str(branche.get("valeur", ""))
        b_crumbs = crumbs + ([b_label] if b_label else [])
        # Regle attachee a la branche
        regle = branche.get("regle")
        if isinstance(regle, dict) and regle.get("id"):
            out.append(
                {
                    "id": regle["id"],
                    "label": " > ".join(b_crumbs),
                    "group": "arbre",
                }
            )
        # Sous-noeud
        if isinstance(branche.get("noeud"), dict):
            _collect_targets_in_node(branche["noeud"], b_crumbs, out)


@method_decorator(staff_member_required, name="dispatch")
class EditRawYamlView(View):
    """POST : remplace le YAML brut entier d'un draft.

    Utilisation principale : editer les blocs hors `arbre` (regles
    partagees, plafonnements, metadata) qui n'ont pas de UI dediee.
    On parse le YAML, on valide la structure, on ecrit. Si une etape
    echoue, on refuse et on renvoie le panneau d'erreurs.
    """

    def post(self, request, tree_pk):
        from io import StringIO

        from ruamel.yaml import YAML
        from ruamel.yaml.error import YAMLError

        from envergo.nitrates.yaml_tree.validator import ValidationError, validate_arbre

        tree = get_object_or_404(DecisionTree, pk=tree_pk)
        err = _check_editable(tree, request.user)
        if err:
            return HttpResponseForbidden(err)
        raw = request.POST.get("contenu_yaml_brut", "")
        if not raw.strip():
            return render(
                request,
                "nitrates_admin/yaml_tree/_validation_panel.html",
                {
                    "tree": tree,
                    "errors": [
                        {
                            "label": "",
                            "message": "Le YAML ne peut pas être vide.",
                            "raw": "",
                            "kind": "structure",
                        }
                    ],
                    "blocked_activation": False,
                },
            )
        # Parse YAML
        yaml = YAML(typ="rt")
        yaml.preserve_quotes = True
        yaml.width = 4096
        try:
            arbre_dict = yaml.load(StringIO(raw))
        except YAMLError as exc:
            return render(
                request,
                "nitrates_admin/yaml_tree/_validation_panel.html",
                {
                    "tree": tree,
                    "errors": [
                        {
                            "label": "Parse YAML",
                            "message": str(exc),
                            "raw": str(exc),
                            "kind": "structure",
                        }
                    ],
                    "blocked_activation": False,
                },
            )
        if not isinstance(arbre_dict, dict):
            return render(
                request,
                "nitrates_admin/yaml_tree/_validation_panel.html",
                {
                    "tree": tree,
                    "errors": [
                        {
                            "label": "",
                            "message": "Le YAML racine doit être un dict.",
                            "raw": "",
                            "kind": "structure",
                        }
                    ],
                    "blocked_activation": False,
                },
            )
        # Validation profonde
        try:
            validate_arbre(arbre_dict, scope=tree.scope)
        except ValidationError as exc:
            return render(
                request,
                "nitrates_admin/yaml_tree/_validation_panel.html",
                {
                    "tree": tree,
                    "errors": [_humanize_error(arbre_dict, e) for e in exc.errors],
                    "blocked_activation": False,
                },
            )
        # OK : on enregistre, avec une revision pour pouvoir undo.
        from django.db import transaction

        with transaction.atomic():
            DecisionTreeRevision.record(
                tree,
                action=DecisionTreeRevision.ACTION_EDIT,
                user=request.user,
                target_path="",
                description="Édition directe du YAML brut",
            )
            tree.contenu = arbre_dict
            tree.contenu_yaml_brut = raw
            tree.save(update_fields=["contenu", "contenu_yaml_brut", "updated_at"])
        # Renvoie un panneau succes + reload
        return _refresh_response(request, "YAML enregistré et validé.")


@method_decorator(staff_member_required, name="dispatch")
class ActivateTreeView(View):
    """POST : valide et publie un draft. Si la validation deep echoue,
    on refuse et on renvoie le panneau d'erreurs ; sinon le draft passe
    en `active`, l'actif courant passe en `archive`.

    L'utilisateur est ensuite redirige vers le viewer du nouvel actif.
    """

    def post(self, request, tree_pk):
        from envergo.nitrates.permissions import can_activate_tree
        from envergo.nitrates.yaml_tree import load_tree_admin
        from envergo.nitrates.yaml_tree.validator import ValidationError, validate_arbre

        tree = get_object_or_404(DecisionTree, pk=tree_pk)
        if tree.status != DecisionTree.STATUS_DRAFT:
            return HttpResponseForbidden("Seul un draft peut etre publie.")
        if not can_activate_tree(request.user, tree):
            return HttpResponseForbidden(
                "L'activation d'un brouillon est réservée aux administrateurs."
            )
        err = _check_editable(tree, request.user)
        if err:
            return HttpResponseForbidden(err)
        arbre = load_tree_admin(tree)
        try:
            validate_arbre(arbre, scope=tree.scope)
        except ValidationError as e:
            # Refus : on renvoie le panneau de validation pour que
            # l'utilisateur voit precisement ce qui bloque.
            return render(
                request,
                "nitrates_admin/yaml_tree/_validation_panel.html",
                {
                    "tree": tree,
                    "errors": [_humanize_error(arbre, err) for err in e.errors],
                    "blocked_activation": True,
                },
            )
        tree.activate()
        # Recharge la page : le draft est maintenant actif, le bandeau
        # change automatiquement (mode lecture sur un actif).
        messages.info(request, f"« {tree.name} » est maintenant l'arbre actif.")
        response = HttpResponse(
            "<div class='yaml-admin__validation-header yaml-admin__validation-header--ok'>"
            "✅ Activé. Rechargement…</div>"
        )
        response["HX-Redirect"] = f"/admin/nitrates/arbre-decision/?tree_id={tree.pk}"
        return response


@method_decorator(staff_member_required, name="dispatch")
class UndoLastView(View):
    """POST : annule la derniere action sur le draft. Restaure l'etat
    capture par la derniere DecisionTreeRevision et reload."""

    def post(self, request, tree_pk):
        tree = get_object_or_404(DecisionTree, pk=tree_pk)
        err = _check_editable(tree, request.user)
        if err:
            return HttpResponseForbidden(err)
        last = (
            DecisionTreeRevision.objects.filter(tree=tree)
            .order_by("-created_at")
            .first()
        )
        if last is None:
            return HttpResponseForbidden("Aucune action a annuler.")
        last.restore()
        return _refresh_response(request, "Action annulée. Rechargement…")


@method_decorator(staff_member_required, name="dispatch")
class RestoreRevisionView(View):
    """POST : restaure une revision specifique (par id) -- pour la page
    historique."""

    def post(self, request, tree_pk):
        tree = get_object_or_404(DecisionTree, pk=tree_pk)
        err = _check_editable(tree, request.user)
        if err:
            return HttpResponseForbidden(err)
        revision_id = request.POST.get("revision_id") or request.GET.get("revision_id")
        try:
            revision_id = int(revision_id)
        except (TypeError, ValueError):
            return HttpResponseForbidden("Identifiant de revision invalide.")
        revision = DecisionTreeRevision.objects.filter(
            tree=tree, pk=revision_id
        ).first()
        if revision is None:
            return HttpResponseForbidden("Revision introuvable.")
        # On garde la trace : restore=False pour ne pas effacer la
        # revision (utile depuis la page historique).
        revision.restore(drop=False)
        return _refresh_response(request, "État restauré. Rechargement…")


@method_decorator(staff_member_required, name="dispatch")
class CancelEditNodeView(View):
    """GET : annule l'edition inline d'un noeud, renvoie la ligne en
    lecture (re-render). Pas de mutation."""

    def get(self, request, tree_pk):
        tree = get_object_or_404(DecisionTree, pk=tree_pk)
        path = _parse_path(request.GET.get("path"))
        node = editor.get_node_at(tree.contenu, path)
        if node is None:
            return HttpResponse(status=204)
        return render(
            request,
            "nitrates_admin/yaml_tree/forms/_node_row.html",
            {
                "tree": tree,
                "node": node,
                "path": path,
                "path_str": "/".join(path),
                "tags": get_tags("noeud", node),
            },
        )


@method_decorator(staff_member_required, name="dispatch")
class NoeudsCiblesView(View):
    """GET : liste les noeuds de l'arbre ACTIF d'un scope donne (national /
    region / zar), en JSON, pour peupler le selecteur `noeud_cible` d'un
    renvoi_arbre dans l'editeur (#222 renvoi cross-arbre cible).

    L'utilisateur choisit l'arbre cible par scope ; on lui propose alors les
    noeuds de l'arbre ACTIF de ce scope (celui qui sera reellement parcouru au
    runtime), charges EN LIVE. Pour region/zar il peut y avoir plusieurs arbres
    actifs (par region_code) : on les agrege tous.

    Reponse : {"noeuds": [{"id": ..., "label": ...}, ...]} triee par label.
    """

    def get(self, request, scope):
        from envergo.nitrates.models import DecisionTree

        scopes_valides = {
            DecisionTree.SCOPE_NATIONAL,
            DecisionTree.SCOPE_REGION,
            DecisionTree.SCOPE_ZAR,
        }
        if scope not in scopes_valides:
            return JsonResponse({"error": f"scope invalide : {scope!r}"}, status=400)
        trees = DecisionTree.objects.filter(
            status=DecisionTree.STATUS_ACTIVE, scope=scope
        )
        noeuds: dict[str, str] = {}  # id -> label (dedup inter-arbres)
        for tree in trees:
            _collecter_noeuds(tree.contenu, noeuds)
        data = [
            {"id": nid, "label": label}
            for nid, label in sorted(noeuds.items(), key=lambda kv: kv[1].lower())
        ]
        return JsonResponse({"noeuds": data})


def _collecter_noeuds(contenu: dict, out: dict) -> None:
    """Remplit `out` {id: label} avec tous les noeuds (formulaire / catalogue /
    catalogue_parametre) de l'arbre. Le label combine l'id et le texte de la
    question quand il existe, pour que le selecteur soit lisible."""

    def walk(node):
        if isinstance(node, dict):
            nid = node.get("id")
            type_noeud = node.get("type_noeud")
            # On ne propose que les vrais noeuds (pas les regles feuilles) :
            # on ne peut atterrir que sur un noeud, pas une regle.
            if nid and type_noeud in (
                "formulaire",
                "catalogue",
                "catalogue_parametre",
            ):
                texte = (node.get("texte") or "").strip()
                out[nid] = f"{nid} — {texte}" if texte else nid
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for it in node:
                walk(it)

    walk(contenu.get("arbre", {}).get("noeud"))
