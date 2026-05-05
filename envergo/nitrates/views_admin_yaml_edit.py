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

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.utils.html import escape
from django.utils.text import slugify
from django.views import View

from envergo.nitrates.models import DecisionTree, DecisionTreeRevision
from envergo.nitrates.yaml_admin import editor
from envergo.nitrates.yaml_admin.grammar import FieldError, get_allowed_child_kinds
from envergo.nitrates.yaml_admin.tags import get_tags


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
    if raw == "True":
        return True
    if raw == "False":
        return False
    return raw


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

    response = render(
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
    )
    response["HX-Retarget"] = f"#node-{slugify(parent_path_str)}"
    response["HX-Reswap"] = "outerHTML"
    if message:
        import json

        response["HX-Trigger"] = json.dumps({"showToast": {"message": message}})
    return response


def _refresh_response(request, message: str) -> HttpResponse:
    """Reponse htmx qui declenche un rechargement de la page courante en
    preservant son URL complete (et donc tous les ?expand=...).

    Le message est passe via Django messages framework -- il sera
    affiche en toaster sur la page rechargee.

    htmx envoie l'URL courante du navigateur dans `HX-Current-URL`, ce
    qui permet de la rejouer en redirect (preserve fold/unfold). En
    fallback on tente Referer, puis HX-Refresh.
    """
    if message:
        messages.info(request, message)
    # `message` peut transiter par les vues a partir de strings construites
    # (ex incluant valeur de branche). On escape pour CodeQL XSS.
    response = HttpResponse(f"<div class='yaml-tree__add-ok'>{escape(message)}</div>")
    current_url = request.META.get("HTTP_HX_CURRENT_URL") or request.META.get(
        "HTTP_REFERER"
    )
    if current_url:
        response["HX-Redirect"] = current_url
    else:
        response["HX-Refresh"] = "true"
    return response


# Suggestions par niveau pour les champs canoniques d'un noeud formulaire.
# Le `champ` (slug technique) doit etre exactement celui-la car le parser
# de la moulinette s'en sert pour mapper a un input utilisateur.
_NIVEAU_SUGGESTIONS = {
    "culture": {
        "champ": "culture",
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
            niveau = request.POST.get("niveau", "").strip() or node.get("niveau")
            new_data["niveau"] = niveau
            new_data["texte"] = request.POST.get("texte", "").strip()
            # `champ` est derive du niveau pour les noeuds formulaire :
            # le parser de la moulinette compte sur cette correspondance
            # 1:1, et l'exposer en saisie libre permet de le casser
            # silencieusement. On accepte un override depuis le POST si
            # fourni (cas avance), sinon on derive automatiquement.
            posted_champ = request.POST.get("champ", "").strip()
            new_data["champ"] = (
                posted_champ or _champ_from_niveau(niveau) or node.get("champ")
            )
            aide = request.POST.get("aide", "").strip()
            if aide:
                new_data["aide"] = aide
        elif node.get("type_noeud") == "catalogue":
            new_data["champ"] = request.POST.get("champ", "").strip()
            new_data["source"] = request.POST.get("source", "").strip() or node.get(
                "source"
            )
            ref = request.POST.get("reference", "").strip()
            if ref:
                new_data["reference"] = ref

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
                },
                status=422,
            )
        # Succes : renvoie la ligne re-rendue (juste le summary visible
        # dans le row, sans les enfants -- htmx swap outerHTML sur le row).
        tree.refresh_from_db()
        node = editor.get_node_at(tree.contenu, path)
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
        return render(
            request,
            "nitrates_admin/yaml_tree/forms/_regle_form.html",
            {
                "tree": tree,
                "regle": branche["regle"],
                "parent_path_str": "/".join(parent_path),
                "valeur": valeur,
                "errors": [],
            },
        )

    def post(self, request, tree_pk):
        tree = get_object_or_404(DecisionTree, pk=tree_pk)
        err = _check_editable(tree, request.user)
        if err:
            return HttpResponseForbidden(err)
        parent_path = _parse_path(request.GET.get("path") or request.POST.get("path"))
        valeur = _parse_valeur(request.GET.get("valeur")) or request.POST.get("valeur")
        branche = editor.get_branche_at(tree.contenu, parent_path, valeur)
        if branche is None or "regle" not in branche:
            return HttpResponseForbidden("Règle introuvable.")

        # Reconstruit new_data depuis le POST.
        new_data: dict = {}
        new_id = request.POST.get("id", "").strip()
        if new_id:
            new_data["id"] = new_id
        rtype = request.POST.get("type", "").strip()
        if rtype:
            new_data["type"] = rtype
        # Periodes : POST contient periodes-{i}-du / periodes-{i}-au /
        # periodes-{i}-regime (optionnel).
        periodes = []
        i = 0
        while True:
            du = request.POST.get(f"periodes-{i}-du", "").strip()
            au = request.POST.get(f"periodes-{i}-au", "").strip()
            regime = request.POST.get(f"periodes-{i}-regime", "").strip()
            if not du and not au and not regime:
                if i == 0:
                    break
                # Ligne suivante vide -> on s'arrete
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
            new_data["periodes"] = periodes
        elif "periodes" in branche["regle"]:
            # L'utilisateur a vide les periodes -> on les retire
            new_data["periodes"] = []
        # Calculatrice : composant + inputs_requis
        composant = request.POST.get("composant", "").strip()
        if composant:
            new_data["composant"] = composant
        inputs_raw = request.POST.get("inputs_requis", "").strip()
        if inputs_raw:
            new_data["inputs_requis"] = [
                x.strip() for x in inputs_raw.split(",") if x.strip()
            ]
        # Champs optionnels scalaires
        for key in (
            "code_prescription",
            "note",
            "source_juridique",
            "message",
            "texte",
            "texte_condition",
            "plafonnement_associe",
        ):
            val = request.POST.get(key, "").strip()
            if val:
                new_data[key] = val
        plafond = request.POST.get("plafond_azote_kg_n_ha", "").strip()
        if plafond:
            try:
                new_data["plafond_azote_kg_n_ha"] = float(plafond)
            except ValueError:
                pass
        # Checkbox a_completer : si non cochee, le navigateur ne l'envoie
        # pas du tout dans le POST. On positionne explicitement False pour
        # ecraser une eventuelle valeur True precedente sur la regle.
        if request.POST.get("a_completer") in ("on", "true", "1"):
            new_data["a_completer"] = True
        else:
            new_data["a_completer"] = False

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
                },
                status=422,
            )
        # Succes : re-render la regle entiere (pas juste une ligne)
        tree.refresh_from_db()
        branche = editor.get_branche_at(tree.contenu, parent_path, valeur)
        return render(
            request,
            "nitrates_admin/yaml_tree/forms/_regle_block.html",
            {
                "tree": tree,
                "regle": branche["regle"],
                "is_editing": True,
                "parent_path": "/".join(parent_path),
                "valeur": valeur,
            },
        )


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
        return render(
            request,
            "nitrates_admin/yaml_tree/forms/_branche_form.html",
            {
                "tree": tree,
                "branche": branche,
                "parent_path_str": "/".join(parent_path),
                "valeur": valeur,
                "errors": [],
                "renvoi_targets": (
                    _list_renvoi_targets(tree.contenu)
                    if "renvoi_vers" in branche
                    else []
                ),
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

        new_valeur_raw = request.POST.get("valeur_new", "").strip()
        new_libelle = request.POST.get("libelle", "").strip()
        new_renvoi = request.POST.get("renvoi_vers_new", "").strip()

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
        new_valeur = _coerce_valeur(new_valeur_raw, type(valeur))

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
            if new_libelle:
                branche["libelle"] = new_libelle
            elif "libelle" in branche:
                del branche["libelle"]
            # Si la branche est de type renvoi_vers, on applique la
            # nouvelle cible si fournie. On ne valide pas ici qu'elle
            # existe dans l'arbre -- le validateur deep le fera.
            if "renvoi_vers" in branche and new_renvoi:
                branche["renvoi_vers"] = new_renvoi
            tree.contenu_yaml_brut = editor._dump_yaml(tree.contenu)
            tree.save(update_fields=["contenu", "contenu_yaml_brut", "updated_at"])

        # Re-render le bloc branche en lecture
        return render(
            request,
            "nitrates_admin/yaml_tree/forms/_branche_block.html",
            {
                "tree": tree,
                "branche": branche,
                "parent_path": "/".join(parent_path),
                "valeur": new_valeur,
                "is_editing": True,
            },
        )


def _render_branche_error(request, tree, branche, parent_path, valeur, field, msg):
    from envergo.nitrates.yaml_admin.grammar import FieldError

    return render(
        request,
        "nitrates_admin/yaml_tree/forms/_branche_form.html",
        {
            "tree": tree,
            "branche": branche,
            "parent_path_str": "/".join(parent_path),
            "valeur": valeur,
            "errors": [FieldError(field, msg)],
        },
        status=422,
    )


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
                "allowed_kinds": allowed,
                "selected_kind": kind,
                "errors": [],
                "form_data": form_data,
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
        data["type_noeud"] = "catalogue"
        data["champ"] = post.get("c_champ", "").strip()
        data["source"] = post.get("c_source", "").strip()
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
    return render(
        request,
        "nitrates_admin/yaml_tree/forms/_add_form.html",
        {
            "tree": tree,
            "parent_path_str": "/".join(parent_path),
            "allowed_kinds": allowed,
            "selected_kind": kind,
            "errors": errors,
            "form_data": form_data or {},
        },
        status=422,
    )


@method_decorator(staff_member_required, name="dispatch")
class CancelAddChildView(View):
    """GET : ferme le formulaire d'ajout (renvoie un fragment vide)."""

    def get(self, request, tree_pk):
        return HttpResponse("")


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
            validate_arbre(arbre)
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
    """Transforme une erreur de validation en dict {label, message, raw}.

    `label` : chemin metier lisible (ex: "Culture principale > Colza >
    période #1").
    `message` : la fin du message d'erreur, sans le chemin technique.
    `raw` : message original, montre au survol pour debug.
    `kind` : "structure" / "renvoi_vers" / "niveau" / "ids" / "date" / ...
    """
    import re

    # Erreur de structure (jsonschema) : "[structure] arbre/.../path : msg"
    m = re.match(r"^\[structure\]\s*(?P<path>\S*)\s*:\s*(?P<msg>.*)$", raw_error)
    if m:
        return {
            "label": _path_to_breadcrumb(arbre, m.group("path")),
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
        label = _find_branch_breadcrumb(arbre, valeur, "renvoi_vers", cible)
        return {
            "label": label,
            "message": f"renvoi vers '{cible}' inconnu",
            "raw": raw_error,
            "kind": "renvoi_vers",
        }

    # Erreur niveau : "[niveau] noeud 'q_xxx' : msg"
    m = re.match(
        r"^\[niveau\]\s*noeud\s*'(?P<nid>[^']+)'\s*:\s*(?P<msg>.*)$", raw_error
    )
    if m:
        nid = m.group("nid")
        label = _find_node_breadcrumb(arbre, nid)
        return {
            "label": label,
            "message": m.group("msg"),
            "raw": raw_error,
            "kind": "niveau",
        }

    # Fallback generique
    m = re.match(r"^\[(?P<kind>\w+)\]\s*(?P<rest>.*)$", raw_error)
    if m:
        return {
            "label": "",
            "message": m.group("rest"),
            "raw": raw_error,
            "kind": m.group("kind"),
        }
    return {"label": "", "message": raw_error, "raw": raw_error, "kind": ""}


def _find_branch_breadcrumb(arbre: dict, valeur: str, key: str, value: str) -> str:
    """Cherche la branche {valeur, key:value} dans l'arbre et renvoie son
    chemin metier lisible."""
    racine = (arbre or {}).get("arbre", {}).get("noeud")
    if not racine:
        return ""
    found = _walk_for_branch(racine, valeur, key, value, [])
    return " > ".join(found) if found else ""


def _walk_for_branch(noeud, target_valeur, target_key, target_value, crumbs):
    if not isinstance(noeud, dict):
        return None
    label = noeud.get("texte") or noeud.get("champ") or noeud.get("id")
    next_crumbs = crumbs + ([str(label)] if label else [])
    for branche in noeud.get("branches") or []:
        if not isinstance(branche, dict):
            continue
        b_label = branche.get("libelle") or str(branche.get("valeur", ""))
        b_crumbs = next_crumbs + ([b_label] if b_label else [])
        if str(branche.get("valeur")) == str(target_valeur) and str(
            branche.get(target_key)
        ) == str(target_value):
            return b_crumbs
        if isinstance(branche.get("noeud"), dict):
            res = _walk_for_branch(
                branche["noeud"], target_valeur, target_key, target_value, b_crumbs
            )
            if res is not None:
                return res
    return None


def _find_node_breadcrumb(arbre: dict, target_id: str) -> str:
    """Cherche un noeud par son id et renvoie son chemin metier lisible."""
    racine = (arbre or {}).get("arbre", {}).get("noeud")
    if not racine:
        return ""
    found = _walk_for_node(racine, target_id, [])
    return " > ".join(found) if found else ""


def _walk_for_node(noeud, target_id, crumbs):
    if not isinstance(noeud, dict):
        return None
    label = noeud.get("texte") or noeud.get("champ") or noeud.get("id")
    next_crumbs = crumbs + ([str(label)] if label else [])
    if noeud.get("id") == target_id:
        return next_crumbs
    for branche in noeud.get("branches") or []:
        if not isinstance(branche, dict):
            continue
        b_label = branche.get("libelle") or str(branche.get("valeur", ""))
        b_crumbs = next_crumbs + ([b_label] if b_label else [])
        if isinstance(branche.get("noeud"), dict):
            res = _walk_for_node(branche["noeud"], target_id, b_crumbs)
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
    if not isinstance(noeud, dict):
        return
    label = noeud.get("texte") or noeud.get("champ") or noeud.get("id")
    next_crumbs = crumbs + ([str(label)] if label else [])
    # On ajoute aussi les noeuds (utile pour renvoyer vers un sous-arbre).
    if noeud.get("id"):
        out.append(
            {
                "id": noeud["id"],
                "label": " > ".join(next_crumbs) if next_crumbs else noeud["id"],
                "group": "arbre",
            }
        )
    for branche in noeud.get("branches") or []:
        if not isinstance(branche, dict):
            continue
        b_label = branche.get("libelle") or str(branche.get("valeur", ""))
        b_crumbs = next_crumbs + ([b_label] if b_label else [])
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


def _path_to_breadcrumb(arbre: dict, raw_path: str) -> str:
    """Convertit un path JSON style "arbre/noeud/branches/1/noeud/branches/0"
    en chemin lisible "Culture principale > Colza > ...".

    On parcourt l'arbre et a chaque noeud on prend `texte` (ou `champ`),
    a chaque branche on prend `libelle` (ou `valeur`).
    """
    if not raw_path:
        return ""
    parts = raw_path.split("/")
    cursor = arbre
    crumbs: list[str] = []
    i = 0
    while i < len(parts):
        seg = parts[i]
        if seg == "arbre":
            cursor = cursor.get("arbre", {}) if isinstance(cursor, dict) else cursor
            i += 1
            continue
        if seg == "noeud":
            cursor = cursor.get("noeud", {}) if isinstance(cursor, dict) else cursor
            if isinstance(cursor, dict):
                label = cursor.get("texte") or cursor.get("champ") or cursor.get("id")
                if label:
                    crumbs.append(str(label))
            i += 1
            continue
        if seg == "branches" and i + 1 < len(parts):
            try:
                idx = int(parts[i + 1])
            except ValueError:
                break
            branches = cursor.get("branches") if isinstance(cursor, dict) else None
            if not branches or idx >= len(branches):
                break
            cursor = branches[idx]
            label = (
                cursor.get("libelle") if isinstance(cursor, dict) else None
            ) or str(cursor.get("valeur") if isinstance(cursor, dict) else "")
            if label:
                crumbs.append(label)
            i += 2
            continue
        if seg == "regle":
            cursor = cursor.get("regle", {}) if isinstance(cursor, dict) else cursor
            i += 1
            continue
        if seg == "periodes" and i + 1 < len(parts):
            try:
                idx = int(parts[i + 1])
            except ValueError:
                break
            crumbs.append(f"période #{idx + 1}")
            periodes = cursor.get("periodes") if isinstance(cursor, dict) else None
            if periodes and idx < len(periodes):
                cursor = periodes[idx]
            i += 2
            continue
        crumbs.append(seg)
        i += 1
    return " > ".join(crumbs) if crumbs else raw_path


@method_decorator(staff_member_required, name="dispatch")
class ActivateTreeView(View):
    """POST : valide et publie un draft. Si la validation deep echoue,
    on refuse et on renvoie le panneau d'erreurs ; sinon le draft passe
    en `active`, l'actif courant passe en `archive`.

    L'utilisateur est ensuite redirige vers le viewer du nouvel actif.
    """

    def post(self, request, tree_pk):
        from envergo.nitrates.yaml_tree import load_tree_admin
        from envergo.nitrates.yaml_tree.validator import ValidationError, validate_arbre

        tree = get_object_or_404(DecisionTree, pk=tree_pk)
        if tree.status != DecisionTree.STATUS_DRAFT:
            return HttpResponseForbidden("Seul un draft peut etre publie.")
        err = _check_editable(tree, request.user)
        if err:
            return HttpResponseForbidden(err)
        arbre = load_tree_admin(tree)
        try:
            validate_arbre(arbre)
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
