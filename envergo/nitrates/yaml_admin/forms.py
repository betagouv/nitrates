"""Formulaires Django pour parser les POST de l'éditeur YAML admin.

3 formulaires prioritaires correspondent aux 3 types de noeuds qu'on
édite inline depuis le viewer :

- `RegleForm` : édition d'une règle (type, périodes, message, etc.)
- `BrancheForm` : édition d'une branche (valeur, libelle, renvoi_vers)
- `NoeudFormulaireForm` : édition d'un noeud formulaire
  (niveau, texte, aide, champ).

Ces formulaires ne rendent **pas** de HTML : les templates dédiés
existent déjà (cf. `nitrates_admin/yaml_tree/forms/`). Leur rôle est
de :
  1. parser le POST en `cleaned_data` (gère les types : float,
     liste CSV, checkbox, périodes répétées) ;
  2. faire les validations locales structurelles (format date JJ/MM,
     id slug-compatible) ;
  3. exposer un dict `to_new_data()` consommable directement par
     `editor.update_node` / `update_regle` / `update_branche`.

La validation **sémantique** (collisions d'id, niveau dans la cascade,
etc.) reste à `editor` via `validate_node_local` / `validate_regle`,
qui ont la connaissance globale de l'arbre.
"""

from __future__ import annotations

import re

from django import forms

# Choix synchronisés avec le schema YAML (cf. yaml_tree/schema.py).
REGLE_TYPES = (
    "interdiction",
    "autorisation_sous_condition",
    "plafonnement",
    "libre",
    "non_applicable",
    "calculatrice",
)
PERIODE_REGIMES = (
    "interdiction",
    "autorisation_sous_condition",
    "plafonnement",
    "libre",
    "non_applicable",
)
NIVEAUX = ("culture", "sous_culture", "type_fertilisant", "complement")

DATE_JJ_MM_RE = re.compile(r"^\d{2}/\d{2}$")
ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _choices(values: tuple[str, ...], blank: bool = False) -> list[tuple[str, str]]:
    """Helper Django : transforme une liste de valeurs en (value, label)
    avec option vide en tête si blank=True."""
    out = [(v, v) for v in values]
    if blank:
        out.insert(0, ("", "— choisir —"))
    return out


def _is_valid_date_or_event(val: str) -> bool:
    """Une borne de période est soit JJ/MM soit un identifiant
    d'événement phénologique (slug). On ne valide pas l'existence de
    l'événement ici, c'est le validator global qui s'en charge."""
    if DATE_JJ_MM_RE.match(val):
        return True
    return bool(ID_RE.match(val))


class _BaseYamlForm(forms.Form):
    """Base : `to_new_data()` retourne le dict consommable par editor."""

    def to_new_data(self) -> dict:
        raise NotImplementedError


class NoeudFormulaireForm(_BaseYamlForm):
    """Édition d'un noeud `type_noeud=formulaire`.

    `champ` est dérivé du niveau côté editor.update_node si vide :
    on accepte une saisie facultative ici.
    """

    id = forms.CharField(required=False)
    niveau = forms.ChoiceField(choices=_choices(NIVEAUX), required=False)
    texte = forms.CharField(required=False)
    aide = forms.CharField(required=False)
    champ = forms.CharField(required=False)

    def to_new_data(self) -> dict:
        cd = self.cleaned_data
        return {
            "id": cd.get("id", "").strip(),
            "niveau": cd.get("niveau", "").strip(),
            "texte": cd.get("texte", "").strip(),
            "aide": cd.get("aide", "").strip(),
            "champ": cd.get("champ", "").strip(),
        }


class BrancheForm(_BaseYamlForm):
    """Édition d'une branche.

    Les champs POST sont nommés `valeur_new`, `libelle`,
    `renvoi_vers_new` (suffixe `_new` car les anciennes valeurs sont
    aussi rendues à des fins d'affichage). On respecte ce nommage ici
    pour que la vue n'ait qu'un `BrancheForm(request.POST)` à faire.
    """

    valeur_new = forms.CharField(required=False)
    libelle = forms.CharField(required=False)
    renvoi_vers_new = forms.CharField(required=False)

    def clean_renvoi_vers_new(self):
        val = self.cleaned_data.get("renvoi_vers_new", "").strip()
        if val and not ID_RE.match(val):
            raise forms.ValidationError(
                "renvoi_vers doit être un id valide (ex: r_xxx, q_xxx, n_xxx)."
            )
        return val

    def to_new_data(self) -> dict:
        cd = self.cleaned_data
        return {
            "valeur_new_raw": cd.get("valeur_new", "").strip(),
            "libelle": cd.get("libelle", "").strip(),
            "renvoi_vers_new": cd.get("renvoi_vers_new", "").strip(),
        }


class RegleForm(_BaseYamlForm):
    """Édition d'une règle.

    Les périodes sont parsées via `periodes-{i}-du / -au / -regime` dans
    le POST (pas via FormSet pour rester simple). `inputs_requis` est
    une chaîne CSV.
    """

    id = forms.CharField(required=False)
    type = forms.ChoiceField(choices=_choices(REGLE_TYPES, blank=True), required=False)
    composant = forms.CharField(required=False)
    inputs_requis = forms.CharField(required=False)
    message = forms.CharField(required=False)
    texte = forms.CharField(required=False)
    texte_condition = forms.CharField(required=False)
    code_prescription = forms.CharField(required=False)
    source_juridique = forms.CharField(required=False)
    note = forms.CharField(required=False)
    plafonnement_associe = forms.CharField(required=False)
    plafond_azote_kg_n_ha = forms.FloatField(required=False)
    a_completer = forms.BooleanField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._periodes: list[dict] = []
        self._periodes_seen = False

    def _parse_periodes(self) -> list[dict]:
        """Lit periodes-0-du, periodes-0-au, periodes-0-regime, etc.
        S'arrête à la première ligne complètement vide."""
        if not self.is_bound:
            return []
        data = self.data
        periodes: list[dict] = []
        i = 0
        while True:
            du = (data.get(f"periodes-{i}-du") or "").strip()
            au = (data.get(f"periodes-{i}-au") or "").strip()
            regime = (data.get(f"periodes-{i}-regime") or "").strip()
            if not du and not au and not regime:
                break
            p: dict = {}
            if du:
                if not _is_valid_date_or_event(du):
                    self.add_error(
                        None,
                        f"Période #{i + 1} : 'du' doit être au format JJ/MM "
                        f"ou un identifiant d'événement.",
                    )
                p["du"] = du
            if au:
                if not _is_valid_date_or_event(au):
                    self.add_error(
                        None,
                        f"Période #{i + 1} : 'au' doit être au format JJ/MM "
                        f"ou un identifiant d'événement.",
                    )
                p["au"] = au
            if regime:
                if regime not in PERIODE_REGIMES:
                    self.add_error(
                        None,
                        f"Période #{i + 1} : régime '{regime}' inconnu.",
                    )
                p["regime"] = regime
            periodes.append(p)
            i += 1
        return periodes

    def clean(self):
        cd = super().clean()
        self._periodes = self._parse_periodes()
        self._periodes_seen = True
        return cd

    @property
    def periodes(self) -> list[dict]:
        if not self._periodes_seen:
            self._periodes = self._parse_periodes()
            self._periodes_seen = True
        return self._periodes

    def to_new_data(self) -> dict:
        cd = self.cleaned_data
        new_data: dict = {}
        if cd.get("id", "").strip():
            new_data["id"] = cd["id"].strip()
        if cd.get("type", "").strip():
            new_data["type"] = cd["type"].strip()
        if self.periodes:
            new_data["periodes"] = self.periodes
        else:
            # Liste vide explicite : signal pour editor que l'utilisateur
            # a vidé les périodes (cf. convention "" = delete).
            new_data["periodes"] = []
        if cd.get("composant", "").strip():
            new_data["composant"] = cd["composant"].strip()
        inputs_raw = cd.get("inputs_requis", "").strip()
        if inputs_raw:
            new_data["inputs_requis"] = [
                x.strip() for x in inputs_raw.split(",") if x.strip()
            ]
        for key in (
            "code_prescription",
            "note",
            "source_juridique",
            "message",
            "texte",
            "texte_condition",
            "plafonnement_associe",
        ):
            val = (cd.get(key) or "").strip()
            if val:
                new_data[key] = val
        plafond = cd.get("plafond_azote_kg_n_ha")
        if plafond is not None:
            new_data["plafond_azote_kg_n_ha"] = float(plafond)
        new_data["a_completer"] = bool(cd.get("a_completer"))
        return new_data
