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

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.views import View

from envergo.nitrates.models import DecisionTree
from envergo.nitrates.yaml_admin import editor
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
        # Periodes : POST contient periodes-{i}-du / periodes-{i}-au
        periodes = []
        i = 0
        while True:
            du = request.POST.get(f"periodes-{i}-du", "").strip()
            au = request.POST.get(f"periodes-{i}-au", "").strip()
            if not du and not au:
                if i == 0:
                    break
                # Ligne suivante vide -> on s'arrete
                break
            if du or au:
                periodes.append({"du": du, "au": au})
            i += 1
        if periodes:
            new_data["periodes"] = periodes
        elif "periodes" in branche["regle"]:
            # L'utilisateur a vide les periodes -> on les retire
            new_data["periodes"] = []
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
        if request.POST.get("a_completer") in ("on", "true", "1"):
            new_data["a_completer"] = True

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
