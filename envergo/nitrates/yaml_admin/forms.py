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
    "mixte",
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
ID_RE = re.compile(r"^[a-z][a-zA-Z0-9_]*$")
# Borne calculatrice : event (+|-) N (jours|semaines|mois). Cf.
# spec_grammaire_calculatrice + validator._BORNE_EVENT_OFFSET_RE.
BORNE_EVENT_OFFSET_RE = re.compile(r"^[a-z][a-zA-Z0-9_]*[+-]\d+(jours|semaines|mois)$")


def _choices(values: tuple[str, ...], blank: bool = False) -> list[tuple[str, str]]:
    """Helper Django : transforme une liste de valeurs en (value, label)
    avec option vide en tête si blank=True."""
    out = [(v, v) for v in values]
    if blank:
        out.insert(0, ("", "— choisir —"))
    return out


def _is_valid_date_or_event(val: str) -> bool:
    """Une borne de période est :
      - une date JJ/MM, ou
      - un identifiant d'événement phénologique / input requis (slug), ou
      - un événement avec offset (cf. spec calculatrice) :
        `event+Njours`, `event-Nsemaines`, `event+Nmois`.

    On ne valide pas l'existence de l'événement / input ici, c'est le
    validator global qui s'en charge.
    """
    if DATE_JJ_MM_RE.match(val):
        return True
    if ID_RE.match(val):
        return True
    return bool(BORNE_EVENT_OFFSET_RE.match(val))


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
    le POST (pas via FormSet pour rester simple).

    `inputs_requis` est parsé via le naming
    `inputs_requis-{i}-id / -label / -type / -placeholder` (objets nouvelle
    grammaire calculatrice, cf. spec form admin calculatrice).

    Le parsing est robuste a la suppression d'un input non-final (cf.
    `_parse_inputs_requis`).
    """

    id = forms.CharField(required=False)
    type = forms.ChoiceField(choices=_choices(REGLE_TYPES, blank=True), required=False)
    composant = forms.CharField(required=False)
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
        self._inputs_requis: list = []
        self._inputs_requis_seen = False

    def _parse_periodes(self) -> list[dict]:
        """Lit periodes-0-du, periodes-0-au, periodes-0-regime,
        periodes-0-masque, periodes-0-condition, etc. S'arrête à la
        première ligne complètement vide."""
        if not self.is_bound:
            return []
        data = self.data
        periodes: list[dict] = []
        i = 0
        while True:
            du = (data.get(f"periodes-{i}-du") or "").strip()
            au = (data.get(f"periodes-{i}-au") or "").strip()
            regime = (data.get(f"periodes-{i}-regime") or "").strip()
            masque_raw = data.get(f"periodes-{i}-masque")
            # checkbox HTML : presente -> coche (truthy), absente -> non coche.
            masque = masque_raw not in (None, "", "false", "0")
            condition = (data.get(f"periodes-{i}-condition") or "").strip()
            if not du and not au and not regime and not masque and not condition:
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
            # On ne pousse `masque` que si true : evite de polluer le YAML
            # avec `masque: false` partout (defaut implicite).
            if masque:
                p["masque"] = True
            # Condition : on valide juste le format ici (le check input_id
            # existe / type=date est fait par le validator global au save).
            # Normalisation : un seul espace autour de l'op.
            if condition:
                from envergo.nitrates.yaml_tree.condition import (
                    ConditionParseError,
                    parse_condition,
                )

                try:
                    parsed = parse_condition(condition)
                except ConditionParseError as exc:
                    self.add_error(
                        None,
                        f"Période #{i + 1} : condition invalide ({exc}).",
                    )
                    p["condition"] = condition
                else:
                    p["condition"] = parsed.normalise()
            periodes.append(p)
            i += 1
        return periodes

    def _parse_inputs_requis(self) -> list:
        """Lit `inputs_requis-{i}-id / -label / -type / -placeholder` (objets
        nouvelle grammaire calculatrice). On collecte d'abord les indices
        presents dans le POST (sans arret a la 1re ligne vide), puis on
        les traite dans l'ordre numerique.

        Pourquoi pas un arret sur ligne vide : quand l'utilisateur supprime
        un input non-final (ex : il garde #1 mais vire #0), un parseur
        sequentiel s'arrete a #0 et perd #1. La presente impl est robuste
        a la suppression d'inputs au milieu.
        """
        if not self.is_bound:
            return []
        data = self.data
        # Trouve tous les indices N presents dans le POST via les noms
        # `inputs_requis-N-...`.
        indices: set[int] = set()
        for key in data.keys():
            m = re.match(r"^inputs_requis-(\d+)-", key)
            if m:
                indices.add(int(m.group(1)))
        out: list = []
        for i in sorted(indices):
            iid = (data.get(f"inputs_requis-{i}-id") or "").strip()
            label = (data.get(f"inputs_requis-{i}-label") or "").strip()
            label_court = (data.get(f"inputs_requis-{i}-label_court") or "").strip()
            itype = (data.get(f"inputs_requis-{i}-type") or "").strip()
            placeholder = (data.get(f"inputs_requis-{i}-placeholder") or "").strip()
            # Bornage optionnel (#126) : limites de saisie JJ/MM.
            bmin = (data.get(f"inputs_requis-{i}-min") or "").strip()
            bmax = (data.get(f"inputs_requis-{i}-max") or "").strip()
            if not (
                iid or label or label_court or itype or placeholder or bmin or bmax
            ):
                continue
            entry: dict = {}
            if iid:
                entry["id"] = iid
            if label:
                entry["label"] = label
            if label_court:
                entry["label_court"] = label_court
            if itype:
                entry["type"] = itype
            if placeholder:
                entry["placeholder"] = placeholder
            if bmin:
                entry["min"] = bmin
            if bmax:
                entry["max"] = bmax
            out.append(entry)
        return out

    def clean(self):
        cd = super().clean()
        self._periodes = self._parse_periodes()
        self._periodes_seen = True
        self._inputs_requis = self._parse_inputs_requis()
        self._inputs_requis_seen = True
        return cd

    @property
    def periodes(self) -> list[dict]:
        if not self._periodes_seen:
            self._periodes = self._parse_periodes()
            self._periodes_seen = True
        return self._periodes

    @property
    def inputs_requis(self) -> list:
        if not self._inputs_requis_seen:
            self._inputs_requis = self._parse_inputs_requis()
            self._inputs_requis_seen = True
        return self._inputs_requis

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
        else:
            # vide explicite : supprime la cle
            new_data["composant"] = None
        # inputs_requis : parses depuis inputs_requis-N-* (cf. _parse_inputs_requis).
        # Toujours pousser une liste (potentiellement vide) pour signaler
        # la mise a jour explicite a editor.update_regle.
        new_data["inputs_requis"] = self.inputs_requis
        # Pour les champs textuels optionnels : on pousse None quand vide pour
        # signaler explicitement la suppression a editor.update_regle (sinon
        # la cle absente = on garde l'ancienne valeur, l'utilisateur ne peut
        # plus vider un champ).
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
            new_data[key] = val if val else None
        plafond = cd.get("plafond_azote_kg_n_ha")
        if plafond is not None:
            new_data["plafond_azote_kg_n_ha"] = float(plafond)
        new_data["a_completer"] = bool(cd.get("a_completer"))
        return new_data
