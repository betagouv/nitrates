"""Mini-browser des arbres YAML en DB.

Endpoint temporaire de visualisation pleine page : liste des trees
(active / draft / archive) puis clic pour afficher le YAML brut avec
coloration syntaxique + folding + selecteur de theme.

Pas d'authentification (mode dev). A retirer ou proteger avant
production publique.
"""

from django.http import Http404
from django.views.generic import DetailView, TemplateView

from envergo.nitrates.models import DecisionTree


class YamlBrowserListView(TemplateView):
    template_name = "nitrates/yaml_browser/list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Trie : actif d'abord, puis drafts les plus recents, puis archives.
        order_status = {
            DecisionTree.STATUS_ACTIVE: 0,
            DecisionTree.STATUS_DRAFT: 1,
            DecisionTree.STATUS_ARCHIVE: 2,
        }
        trees = list(DecisionTree.objects.all().order_by("-updated_at"))
        trees.sort(key=lambda t: (order_status.get(t.status, 9), -t.id))
        ctx["trees"] = trees
        return ctx


class YamlBrowserDetailView(DetailView):
    model = DecisionTree
    template_name = "nitrates/yaml_browser/detail.html"
    context_object_name = "tree"

    def get_object(self, queryset=None):
        pk = self.kwargs.get("pk")
        try:
            return DecisionTree.objects.get(pk=pk)
        except DecisionTree.DoesNotExist as e:
            raise Http404(f"Tree {pk} introuvable") from e

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        tree = ctx["tree"]
        ctx["yaml_brut"] = tree.contenu_yaml_brut or ""
        ctx["lines"] = ctx["yaml_brut"].count("\n") + 1
        return ctx
