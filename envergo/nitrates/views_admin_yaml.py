"""Viewer admin de l'arbre de decision YAML.

Une seule vue : `/admin/nitrates/arbre-decision/`. Toggle vue via `?vue=`.
Filtre rapide via `?filtre=` (un tag a la fois). Etat de fold dans
`?expand=` (cumulables) et `?expand_deep=` (recursif). Selection du tree
via `?tree_id=<pk>` (defaut : tree actif). SSR pur, pas de JS.

Source de verite : la table `DecisionTree`.
"""

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import TemplateView
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import YamlLexer

from envergo.nitrates.models import DecisionTree
from envergo.nitrates.yaml_admin.flatten import iter_entries
from envergo.nitrates.yaml_admin.fold import compute_open_paths
from envergo.nitrates.yaml_admin.tags import (
    QUICK_FILTER_KEYS,
    QUICK_FILTERS,
    get_tags,
    has_a_completer,
)
from envergo.nitrates.yaml_tree import load_tree_admin, load_tree_raw

_VUES = {"arbre", "brut", "split"}
_MODES = {"lecture", "edition"}


@method_decorator(staff_member_required, name="dispatch")
class YamlTreeView(TemplateView):
    template_name = "nitrates_admin/yaml_tree/tree.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        vue = self.request.GET.get("vue", "arbre")
        if vue not in _VUES:
            vue = "arbre"
        filtre = self.request.GET.get("filtre", "")
        if filtre not in QUICK_FILTER_KEYS:
            filtre = ""

        # Sets de paths a deplier explicitement (cumul de plusieurs occurrences
        # du parametre GET). Tronques pour eviter les abus.
        expand = set(self.request.GET.getlist("expand")[:200])
        expand_deep = set(self.request.GET.getlist("expand_deep")[:200])

        # Selection du tree : ?tree_id=<pk> sinon le tree actif.
        tree_id = self.request.GET.get("tree_id")
        tree = _resolve_tree(tree_id)
        if tree is None:
            ctx.update(
                {
                    "no_tree": True,
                    "vue": vue,
                    "filtre": filtre,
                    "quick_filters": QUICK_FILTERS,
                    "querystring_base": _querystring_base(vue, filtre, None),
                }
            )
            return ctx

        # Mode lecture/edition. Le mode edition n'est autorise que sur des
        # drafts. Si l'utilisateur force `?mode=edition` sur un autre statut,
        # on retombe silencieusement en lecture.
        mode = self.request.GET.get("mode", "lecture")
        if mode not in _MODES:
            mode = "lecture"
        if mode == "edition" and tree.status != DecisionTree.STATUS_DRAFT:
            mode = "lecture"

        # Lock : si on entre en mode edition, on tente d'acquerir le lock.
        # Si refuse (autre admin en train d'editer), on retombe en lecture
        # avec un message explicatif via le contexte.
        lock_blocked_by = None
        if mode == "edition":
            if not tree.acquire_lock(self.request.user):
                # Re-charger pour avoir locked_by/locked_at a jour
                tree.refresh_from_db()
                lock_blocked_by = tree.locked_by
                mode = "lecture"

        active_tree = (
            DecisionTree.objects.filter(status=DecisionTree.STATUS_ACTIVE)
            .only("pk", "name")
            .first()
        )

        arbre = load_tree_admin(tree)
        racine = arbre.get("arbre", {}).get("noeud") or {}

        entries = list(iter_entries(arbre))
        items = [
            {
                "kind": e.kind,
                "depth": e.depth,
                "path": e.path,
                "path_str": e.path_str,
                "data": e.data,
                "tags": get_tags(e.kind, e.data if isinstance(e.data, dict) else {}),
            }
            for e in entries
        ]

        open_paths = compute_open_paths(
            racine, filtre=filtre, expand=expand, expand_deep=expand_deep
        )

        ctx.update(
            {
                "metadata": arbre.get("metadata") or {},
                "racine": racine,
                "items": items,
                "vue": vue,
                "filtre": filtre,
                "expand": sorted(expand),
                "expand_deep": sorted(expand_deep),
                "open_paths": open_paths,
                "quick_filters": QUICK_FILTERS,
                "stats": _compute_stats(items),
                "querystring_base": _querystring_base(vue, filtre, tree.pk),
                "tree": tree,
                "active_tree": active_tree,
                "is_viewing_active": active_tree and active_tree.pk == tree.pk,
                "mode": mode,
                "is_editing": mode == "edition",
                "lock_blocked_by": lock_blocked_by,
                "edited_origin_name": _edited_origin_name(tree),
                "recent_revisions": (
                    list(tree.revisions.order_by("-created_at")[:5])
                    if mode == "edition"
                    else []
                ),
            }
        )

        if vue in {"brut", "split"}:
            raw = load_tree_raw(tree)
            formatter = HtmlFormatter(
                cssclass="yaml-raw",
                linenos="inline",
                wrapcode=True,
                style="monokai",
            )
            ctx["raw_html"] = highlight(raw, YamlLexer(), formatter)
            ctx["raw_css"] = formatter.get_style_defs(".yaml-raw")
            ctx["arbre_has_a_completer"] = has_a_completer(racine)

        return ctx


@method_decorator(staff_member_required, name="dispatch")
class EditActiveView(View):
    """Entry point pour "Editer l'arbre actif".

    GET ou POST : trouve ou cree le draft d'edition de l'utilisateur sur
    l'arbre actif courant, redirige vers le viewer en mode edition.
    UX : l'utilisateur ne voit pas l'existence du draft, il croit
    "editer l'arbre actif" -- en realite on travaille sur un clone.
    """

    def get(self, request, *args, **kwargs):
        return self._do(request)

    def post(self, request, *args, **kwargs):
        return self._do(request)

    def _do(self, request):
        from django.http import HttpResponseForbidden

        from envergo.nitrates.permissions import can_edit_active

        if not can_edit_active(request.user):
            return HttpResponseForbidden(
                "L'édition de l'arbre actif est réservée aux administrateurs. "
                "Vous pouvez cloner l'arbre actif pour créer votre propre brouillon."
            )
        draft = DecisionTree.find_or_create_edit_draft(request.user)
        if draft is None:
            return HttpResponseRedirect(reverse("nitrates_admin_yaml_tree"))
        url = reverse("nitrates_admin_yaml_tree") + f"?tree_id={draft.pk}&mode=edition"
        return HttpResponseRedirect(url)


@method_decorator(staff_member_required, name="dispatch")
class CancelEditView(View):
    """Sort du mode edition. Libere le lock si l'utilisateur le detenait.

    Le draft sous-jacent reste en DB (pas de suppression) -- l'utilisateur
    pourra le reprendre via "Editer l'arbre actif" plus tard.

    Redirige vers le viewer de l'arbre actif (UX : retour au point de
    depart, sans exposer le draft).
    """

    def post(self, request, pk, *args, **kwargs):
        tree = get_object_or_404(DecisionTree, pk=pk)
        tree.release_lock(request.user)
        active = (
            DecisionTree.objects.filter(status=DecisionTree.STATUS_ACTIVE)
            .only("pk")
            .first()
        )
        if active is not None:
            return HttpResponseRedirect(
                reverse("nitrates_admin_yaml_tree") + f"?tree_id={active.pk}"
            )
        return HttpResponseRedirect(reverse("nitrates_admin_yaml_tree"))


@method_decorator(staff_member_required, name="dispatch")
class RenameTreeView(View):
    """Renomme un tree depuis la page d'edition (bandeau viewer).

    POST `/admin/nitrates/arbre-decision/<pk>/renommer/`
    Body : `name=<nouveau_nom>`

    Refuse si le nouveau nom est vide ou entre en collision avec un autre
    tree.
    """

    def post(self, request, pk, *args, **kwargs):
        tree = get_object_or_404(DecisionTree, pk=pk)
        new_name = (request.POST.get("name") or "").strip()
        if not new_name:
            return HttpResponseRedirect(
                reverse("nitrates_admin_yaml_tree") + f"?tree_id={tree.pk}"
            )
        # Collision : si un autre tree porte deja ce nom, on ajoute un
        # suffixe numerique pour eviter le doublon.
        if DecisionTree.objects.filter(name=new_name).exclude(pk=tree.pk).exists():
            base = new_name
            n = 2
            while (
                DecisionTree.objects.filter(name=f"{base} ({n})")
                .exclude(pk=tree.pk)
                .exists()
            ):
                n += 1
            new_name = f"{base} ({n})"
        tree.name = new_name
        tree.save(update_fields=["name", "updated_at"])
        return HttpResponseRedirect(
            reverse("nitrates_admin_yaml_tree") + f"?tree_id={tree.pk}"
        )


@method_decorator(staff_member_required, name="dispatch")
class CloneConfirmView(TemplateView):
    """Page intermediaire de confirmation pour le clone depuis la liste admin.

    Utile parce que les `<a>` de la colonne actions admin ne peuvent pas
    embarquer un csrf token (pas d'acces a la request). On passe donc par
    un GET qui affiche un formulaire POST CSRF-protege.
    """

    template_name = "nitrates_admin/clone_confirm.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["source"] = get_object_or_404(DecisionTree, pk=kwargs["pk"])
        return ctx


@method_decorator(staff_member_required, name="dispatch")
class CreateDraftView(View):
    """Cree un draft par clonage d'un tree existant.

    POST `/admin/nitrates/arbre-decision/draft/nouveau/?from=<pk>`

    Source par defaut : l'arbre actif. Si `from` est fourni, on clone ce
    tree-la (peu importe son statut). Le draft cree porte un nom auto
    `<source.name> (copy)` (suffixe `(copy 2)`, `(copy 3)`... si collision).
    Redirige vers le viewer du draft cree.
    """

    def post(self, request, *args, **kwargs):
        from_id = request.GET.get("from") or request.POST.get("from")
        if from_id:
            source = get_object_or_404(DecisionTree, pk=from_id)
        else:
            source = DecisionTree.objects.filter(
                status=DecisionTree.STATUS_ACTIVE
            ).first()
            if source is None:
                return HttpResponseRedirect(reverse("nitrates_admin_yaml_tree"))

        draft = DecisionTree.clone_to_draft(source, user=request.user)
        url = reverse("nitrates_admin_yaml_tree") + f"?tree_id={draft.pk}"
        return HttpResponseRedirect(url)


def _edited_origin_name(tree: DecisionTree) -> str:
    """Pour l'UX d'edition : le nom de l'arbre source que l'utilisateur
    croit editer. Si le draft a ete cree depuis l'actif, c'est le nom de
    cet actif. Sinon (parent archive ou null), le nom du draft lui-meme.
    """
    if tree.status == DecisionTree.STATUS_DRAFT and tree.parent_id:
        return tree.parent.name
    return tree.name


def _resolve_tree(tree_id) -> DecisionTree | None:
    """Retourne le DecisionTree cible. Si tree_id est fourni, on le charge
    (lance 404 si introuvable). Sinon on retourne l'actif courant.
    Retourne None si rien n'est dispo (DB vide)."""
    if tree_id:
        try:
            return DecisionTree.objects.get(pk=tree_id)
        except (DecisionTree.DoesNotExist, ValueError):
            return None
    return DecisionTree.objects.filter(status=DecisionTree.STATUS_ACTIVE).first()


def _querystring_base(vue: str, filtre: str, tree_pk) -> str:
    """Querystring pour les liens de la barre de fold (sans expand/expand_deep,
    ces deux la sont gerees au cas par cas dans le template)."""
    parts = []
    if vue and vue != "arbre":
        parts.append(f"vue={vue}")
    if filtre:
        parts.append(f"filtre={filtre}")
    if tree_pk is not None:
        parts.append(f"tree_id={tree_pk}")
    return "&".join(parts)


def _compute_stats(items: list[dict]) -> dict:
    n_noeuds = sum(1 for it in items if it["kind"] == "noeud")
    n_regles = sum(1 for it in items if it["kind"] == "regle")
    n_renvois = sum(1 for it in items if it["kind"] == "renvoi_vers")
    n_a_completer = sum(
        1
        for it in items
        if isinstance(it["data"], dict) and it["data"].get("a_completer") is True
    )
    return {
        "noeuds": n_noeuds,
        "regles": n_regles,
        "renvois": n_renvois,
        "a_completer": n_a_completer,
    }
