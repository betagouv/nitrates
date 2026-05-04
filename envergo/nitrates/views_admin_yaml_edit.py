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
    response = HttpResponse(f"<div class='yaml-tree__add-ok'>{message}</div>")
    current_url = request.META.get("HTTP_HX_CURRENT_URL") or request.META.get(
        "HTTP_REFERER"
    )
    if current_url:
        response["HX-Redirect"] = current_url
    else:
        response["HX-Refresh"] = "true"
    return response


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
            new_data["niveau"] = request.POST.get("niveau", "").strip() or node.get(
                "niveau"
            )
            new_data["texte"] = request.POST.get("texte", "").strip()
            new_data["champ"] = request.POST.get("champ", "").strip()
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

        return _refresh_response(request, f"Branche {valeur!r} ajoutée. Rechargement…")


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
        data["texte"] = post.get("c_texte", "").strip()
        data["champ"] = post.get("c_champ", "").strip()
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
        return _refresh_response(
            request, f"Branche {valeur!r} supprimée. Rechargement…"
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
        return _refresh_response(
            request, f"Nœud {path[-1] if path else ''} supprimé. Rechargement…"
        )


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
