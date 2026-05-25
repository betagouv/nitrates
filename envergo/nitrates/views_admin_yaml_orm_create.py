"""Création htmx d'objets ORM référentiels depuis l'éditeur YAML d'arbre.

Issue #103 : depuis les `<select>` de l'éditeur, un bouton "+" déplie
un mini-form htmx qui crée un objet ORM (CodePrescription, NoteReglementaire,
EvenementPhenologique, Culture, Fertilisant) et le réinjecte dans le select
parent via hx-swap-oob.

Pour les modèles avec FK (Culture, Fertilisant), les FK sont auto-résolues
depuis le chemin parent dans l'arbre YAML : on remonte les niveaux
`categorie_culture`, `categorie_fertilisant`, `occupation_sol` et on
récupère la valeur choisie. Si la FK requise n'est pas résolvable,
on refuse la création (l'utilisateur doit d'abord créer le parent).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from django.contrib.admin.views.decorators import staff_member_required
from django.db import IntegrityError, transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View

from envergo.nitrates.models import (
    BrancheCulturale,
    CategorieCulture,
    CodePrescription,
    Culture,
    DecisionTree,
    EvenementPhenologique,
    Fertilisant,
    NoteReglementaire,
)

# ─── Résolution du contexte parent dans l'arbre YAML ─────────────────────────


def _path_choices(arbre: dict, path: tuple[str, ...]) -> dict[str, str]:
    """Pour chaque noeud du chemin, retourne {champ: valeur_choisie}.

    Exemple si on est sur ...q_occupation_sol/culture_principale/q_categorie_culture/
    culture_de_printemps/q_sous_culture, on retourne :
        {"occupation_sol": "culture_principale",
         "categorie_culture": "culture_de_printemps"}

    Le `champ` provient du noeud formulaire ; la `valeur` provient de la
    branche descendante (= le choix qui a mené au noeud suivant).
    """
    racine = (arbre or {}).get("arbre", {}).get("noeud")
    if not racine or not path or racine.get("id") != path[0]:
        return {}
    choices: dict[str, str] = {}
    current = racine
    for nid in path[1:]:
        for branche in current.get("branches") or []:
            if (
                isinstance(branche, dict)
                and isinstance(branche.get("noeud"), dict)
                and branche["noeud"].get("id") == nid
            ):
                champ = current.get("champ")
                val = branche.get("valeur")
                if champ and val is not None:
                    choices[champ] = str(val)
                current = branche["noeud"]
                break
        else:
            break
    return choices


# ─── Configuration par modèle ───────────────────────────────────────────────


@dataclass(frozen=True)
class OrmModelSpec:
    """Décrit un modèle ORM créable depuis l'éditeur YAML.

    - `key` : slug url-safe utilisé dans l'URL htmx
    - `model` : la classe ORM Django
    - `label` : libellé humain pour le panel ("Nouvelle note", etc.)
    - `user_fields` : champs saisis librement par l'utilisateur
    - `fk_resolvers` : {nom_champ_orm: nom_champ_yaml} -- pour chaque FK ORM,
       on regarde le `choices[champ_yaml]` extrait du chemin parent
    - `to_choice` : callable qui transforme l'instance créée en
       (value, label) pour le <option> à réinjecter dans le select parent
    """

    key: str
    model: type
    label: str
    user_fields: tuple[tuple[str, str], ...]  # (name, label_humain)
    fk_resolvers: dict[str, str]
    to_choice: Callable[[object], tuple[str, str]]


def _culture_resolve_fk(choices: dict[str, str]) -> dict:
    """Pour Culture : occupation_sol (str enum), categorie (FK CategorieCulture),
    branche_culturale (FK BrancheCulturale).

    On résout depuis le chemin parent : `occupation_sol` est une enum,
    on prend la valeur brute. `categorie_culture` et `branche_culturale`
    sont des FK, on cherche par `identifiant`.
    """
    resolved: dict = {}
    if "occupation_sol" in choices:
        resolved["occupation_sol"] = choices["occupation_sol"]
    if "categorie_culture" in choices:
        try:
            resolved["categorie"] = CategorieCulture.objects.get(
                identifiant=choices["categorie_culture"]
            )
        except CategorieCulture.DoesNotExist:
            return {}
    if "branche_culturale" in choices:
        try:
            resolved["branche_culturale"] = BrancheCulturale.objects.get(
                identifiant=choices["branche_culturale"]
            )
        except BrancheCulturale.DoesNotExist:
            return {}
    return resolved


def _fertilisant_resolve_fk(choices: dict[str, str]) -> dict:
    """Pour Fertilisant : categorie (enum CategorieFertilisant, str)."""
    resolved: dict = {}
    if "categorie_fertilisant" in choices:
        resolved["categorie"] = choices["categorie_fertilisant"]
    return resolved


SPECS: dict[str, OrmModelSpec] = {
    "code_prescription": OrmModelSpec(
        key="code_prescription",
        model=CodePrescription,
        label="Nouveau code de prescription",
        user_fields=(
            ("identifiant", "Identifiant (ex: pc16)"),
            ("mots_cles", "Mots-clés (court)"),
            ("texte_court", "Texte court"),
            ("texte_redaction_initiale", "Texte de rédaction initiale"),
        ),
        fk_resolvers={},
        to_choice=lambda obj: (obj.identifiant, f"{obj.identifiant} — {obj.mots_cles}"),
    ),
    "note": OrmModelSpec(
        key="note",
        model=NoteReglementaire,
        label="Nouvelle note réglementaire",
        user_fields=(
            ("identifiant", "Identifiant (ex: note_14)"),
            ("libelle_court", "Libellé court"),
            ("condition_declenchement", "Condition de déclenchement"),
        ),
        fk_resolvers={},
        to_choice=lambda obj: (
            obj.identifiant,
            f"{obj.identifiant} — {obj.libelle_court}",
        ),
    ),
    "evenement_phenologique": OrmModelSpec(
        key="evenement_phenologique",
        model=EvenementPhenologique,
        label="Nouvel événement phénologique",
        user_fields=(
            ("identifiant", "Identifiant (ex: floraison_colza)"),
            ("libelle_public", "Libellé public"),
            ("date_calendrier", "Date conventionnelle (JJ/MM, optionnel)"),
        ),
        fk_resolvers={},
        to_choice=lambda obj: (obj.identifiant, obj.libelle_public),
    ),
    "culture": OrmModelSpec(
        key="culture",
        model=Culture,
        label="Nouvelle culture (sous-culture)",
        user_fields=(
            ("identifiant", "Identifiant (ex: epeautre)"),
            ("libelle_public", "Libellé public"),
        ),
        fk_resolvers={
            "categorie": "categorie_culture",
            "branche_culturale": "branche_culturale",
            "occupation_sol": "occupation_sol",
        },
        to_choice=lambda obj: (obj.identifiant, obj.libelle_public),
    ),
    "fertilisant": OrmModelSpec(
        key="fertilisant",
        model=Fertilisant,
        label="Nouveau fertilisant (sous-fertilisant)",
        user_fields=(
            ("identifiant", "Identifiant (ex: lisier_porcin_dilue)"),
            ("libelle_public", "Libellé public"),
            (
                "type_reglementaire",
                "Type réglementaire (type_Ia / type_Ib / type_II / type_III)",
            ),
        ),
        fk_resolvers={"categorie": "categorie_fertilisant"},
        to_choice=lambda obj: (obj.identifiant, obj.libelle_public),
    ),
}


def _resolve_fks(spec: OrmModelSpec, choices: dict[str, str]) -> tuple[dict, list[str]]:
    """Pour les modèles avec FK, applique le resolver dédié.
    Renvoie (kwargs_pre_remplis, fk_manquantes_pour_affichage)."""
    if spec.key == "culture":
        resolved = _culture_resolve_fk(choices)
    elif spec.key == "fertilisant":
        resolved = _fertilisant_resolve_fk(choices)
    else:
        resolved = {}
    missing = []
    for orm_field, yaml_champ in spec.fk_resolvers.items():
        if orm_field not in resolved:
            missing.append(yaml_champ)
    return resolved, missing


# ─── Vues htmx ──────────────────────────────────────────────────────────────


@method_decorator(staff_member_required, name="dispatch")
class OrmCreatePanelView(View):
    """GET : renvoie un fragment htmx contenant le mini-form de création.
    POST : crée l'objet ORM et renvoie un fragment qui (a) ferme le panel
    et (b) injecte la nouvelle <option selected> dans le <select> cible
    via hx-swap-oob.

    Query params attendus :
        tree_pk : id du DecisionTree (pour résoudre le contexte parent)
        parent_path : chemin slash-séparé du noeud parent dans l'arbre
        target_select : selector CSS du <select> à mettre à jour (côté front)
    """

    def get(self, request, model_key):
        spec = SPECS.get(model_key)
        if not spec:
            return HttpResponseBadRequest(f"Modèle inconnu : {model_key}")
        tree_pk = request.GET.get("tree_pk", "")
        parent_path = request.GET.get("parent_path", "")
        target_select = request.GET.get("target_select", "")

        resolved, missing = self._resolve(spec, tree_pk, parent_path)
        if missing:
            return render(
                request,
                "nitrates_admin/yaml_tree/forms/_orm_create_blocked.html",
                {
                    "spec": spec,
                    "missing": missing,
                    "target_select": target_select,
                },
                status=200,
            )
        return render(
            request,
            "nitrates_admin/yaml_tree/forms/_orm_create_panel.html",
            {
                "spec": spec,
                "resolved": self._humanize_resolved(resolved),
                "target_select": target_select,
                "tree_pk": tree_pk,
                "parent_path": parent_path,
                "model_key": model_key,
            },
        )

    def post(self, request, model_key):
        spec = SPECS.get(model_key)
        if not spec:
            return HttpResponseBadRequest(f"Modèle inconnu : {model_key}")
        tree_pk = request.POST.get("tree_pk", "")
        parent_path = request.POST.get("parent_path", "")
        target_select = request.POST.get("target_select", "")

        resolved, missing = self._resolve(spec, tree_pk, parent_path)
        if missing:
            return HttpResponseBadRequest(
                f"FK non résolvables depuis le chemin parent : {missing}"
            )

        kwargs = dict(resolved)
        for name, _label in spec.user_fields:
            raw = (request.POST.get(name) or "").strip()
            if raw:
                kwargs[name] = raw

        errors: list[str] = []
        if not kwargs.get("identifiant"):
            errors.append("L'identifiant est obligatoire.")
        if errors:
            return render(
                request,
                "nitrates_admin/yaml_tree/forms/_orm_create_panel.html",
                {
                    "spec": spec,
                    "resolved": self._humanize_resolved(resolved),
                    "target_select": target_select,
                    "tree_pk": tree_pk,
                    "parent_path": parent_path,
                    "model_key": model_key,
                    "errors": errors,
                    "form_data": kwargs,
                },
                status=422,
            )

        try:
            with transaction.atomic():
                obj = spec.model(**kwargs)
                obj.full_clean()
                obj.save()
        except IntegrityError as exc:
            return render(
                request,
                "nitrates_admin/yaml_tree/forms/_orm_create_panel.html",
                {
                    "spec": spec,
                    "resolved": self._humanize_resolved(resolved),
                    "target_select": target_select,
                    "tree_pk": tree_pk,
                    "parent_path": parent_path,
                    "model_key": model_key,
                    "errors": [f"Identifiant déjà utilisé : {exc}"],
                    "form_data": kwargs,
                },
                status=422,
            )
        except Exception as exc:  # ValidationError full_clean
            return render(
                request,
                "nitrates_admin/yaml_tree/forms/_orm_create_panel.html",
                {
                    "spec": spec,
                    "resolved": self._humanize_resolved(resolved),
                    "target_select": target_select,
                    "tree_pk": tree_pk,
                    "parent_path": parent_path,
                    "model_key": model_key,
                    "errors": [str(exc)],
                    "form_data": kwargs,
                },
                status=422,
            )

        value, label = spec.to_choice(obj)
        return render(
            request,
            "nitrates_admin/yaml_tree/forms/_orm_create_success.html",
            {
                "spec": spec,
                "target_select": target_select,
                "value": value,
                "label": label,
            },
        )

    # ─── Helpers ───────────────────────────────────────────────────────────

    def _resolve(
        self, spec: OrmModelSpec, tree_pk: str, parent_path: str
    ) -> tuple[dict, list[str]]:
        """Charge l'arbre et résout les FK ORM auto-déduites du chemin."""
        if not spec.fk_resolvers:
            return {}, []
        try:
            tree = DecisionTree.objects.get(pk=int(tree_pk))
        except (DecisionTree.DoesNotExist, ValueError, TypeError):
            return {}, list(spec.fk_resolvers.values())
        path_tuple = tuple(p for p in parent_path.split("/") if p)
        choices = _path_choices(tree.contenu or {}, path_tuple)
        return _resolve_fks(spec, choices)

    def _humanize_resolved(self, resolved: dict) -> list[tuple[str, str]]:
        """Pour affichage read-only dans le panel."""
        out = []
        for key, val in resolved.items():
            if hasattr(val, "identifiant"):
                out.append((key, val.identifiant))
            else:
                out.append((key, str(val)))
        return out


def _path_choices_for_test(arbre, path):
    """Exposé pour les tests unitaires (le `_` initial est convention privée
    mais ce helper est lourd à tester sans wrapper public)."""
    return _path_choices(arbre, path)
