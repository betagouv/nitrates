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
