"""Viewer admin de l'arbre de decision YAML.

Une seule vue : `/admin/nitrates/arbre-decision/`. Toggle vue via `?vue=`.
Filtre rapide via `?filtre=` (un tag a la fois). Etat de fold dans
`?expand=` (cumulables) et `?expand_deep=` (recursif). Selection du tree
via `?tree_id=<pk>` (defaut : tree actif). SSR pur, pas de JS.

Source de verite : la table `DecisionTree`.
"""

from django.contrib.admin.views.decorators import staff_member_required
from django.utils.decorators import method_decorator
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
            }
        )

        if vue in {"brut", "split"}:
            raw = load_tree_raw(tree)
            formatter = HtmlFormatter(
                cssclass="yaml-raw", linenos="inline", wrapcode=True
            )
            ctx["raw_html"] = highlight(raw, YamlLexer(), formatter)
            ctx["raw_css"] = formatter.get_style_defs(".yaml-raw")
            ctx["arbre_has_a_completer"] = has_a_completer(racine)

        return ctx


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
