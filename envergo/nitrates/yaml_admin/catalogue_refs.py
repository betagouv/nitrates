"""Registre typé des références catalogue.

Source unique de vérité pour les noeuds `type_noeud: catalogue` :

- côté **runtime** (`regulations.arbre_decision._resoudre_catalogue`),
  ce registre fournit la fonction `resolve(ctx)` qui transforme un
  `BesoinCatalogue` en valeur concrète (bool ou string).
- côté **éditeur YAML** (admin), ce registre fournit le label, la
  description, le `champ` canonique et les valeurs de branches
  attendues, pour rendre un select dans le formulaire d'ajout/édition
  de noeud catalogue.

Ajouter une nouvelle référence catalogue = ajouter une entrée dans
`CATALOGUE_RESOLVERS`. Un new-comer n'a qu'un seul fichier à toucher
pour brancher un nouveau dataset (la fonction `resolve` peut taper
PostGIS, un mapping CSV, un calcul, etc.).

NB: la sentinelle `CATALOGUE_NON_RESOLVABLE` est exposée ici plutôt
qu'à `arbre_decision` parce qu'elle fait partie du contrat d'un
résolveur (« je ne peux pas trancher, retombe sur non_disponible »).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from envergo.geodata.models import MAP_TYPES, Zone
from envergo.nitrates.zonage_montagne import (
    est_zone_montagne_d113_14,
    note_7_vs_note_6_pour_commune,
    zonage_montagne_pour_commune,
)
from envergo.nitrates.zonage_note_5 import zone_note_5_pour_commune

# Sentinelle retournée par un résolveur quand on ne sait pas trancher
# (dataset SIG manquant, code INSEE absent, etc.). L'évaluator l'attrape
# et bascule en RESULTS.non_disponible.
CATALOGUE_NON_RESOLVABLE = object()


@dataclass(frozen=True)
class ResolveContext:
    """Données dont un résolveur peut avoir besoin pour trancher.

    Construit par `arbre_decision` à partir du `catalog` Envergo et du
    `form_kwargs["data"]` du form additionnel.
    """

    code_insee: str | None
    lng_lat: Any | None  # GEOSGeometry Point ou None


@dataclass(frozen=True)
class CatalogueResolver:
    """Description complète d'une référence catalogue.

    `resolve` reçoit un `ResolveContext` et retourne la valeur à
    injecter dans le contexte de parcours, ou `CATALOGUE_NON_RESOLVABLE`
    si le résolveur ne peut pas trancher.
    """

    reference: str  # clé YAML (`reference: ...`)
    label: str  # libellé court pour le select de l'éditeur
    description: str  # texte d'aide (tooltip)
    champ: str  # `champ` canonique à utiliser dans le YAML
    valeurs_branches: tuple[str, ...]  # valeurs attendues pour les branches enfants
    resolve: Callable[[ResolveContext], Any]


# ─── Résolveurs ───────────────────────────────────────────────────────


def _resolve_zone_vulnerable_nitrates(ctx: ResolveContext) -> Any:
    if ctx.lng_lat is None:
        return CATALOGUE_NON_RESOLVABLE
    return Zone.objects.filter(
        map__map_type=MAP_TYPES.zv_nitrates, geometry__intersects=ctx.lng_lat
    ).exists()


def _resolve_zone_note_5(ctx: ResolveContext) -> Any:
    return zone_note_5_pour_commune(ctx.code_insee)


def _resolve_zone_montagne_d113_14(ctx: ResolveContext) -> Any:
    return est_zone_montagne_d113_14(ctx.code_insee)


def _resolve_zonage_prairie_III(ctx: ResolveContext) -> Any:
    return zonage_montagne_pour_commune(ctx.code_insee, variante="pyrenees_atl")


def _resolve_zone_note_7_montagne(ctx: ResolveContext) -> Any:
    return zonage_montagne_pour_commune(ctx.code_insee, variante="elargie")


def _resolve_zone_note_7_vs_note_6(ctx: ResolveContext) -> Any:
    return note_7_vs_note_6_pour_commune(ctx.code_insee, variante="elargie")


# ─── Registre ─────────────────────────────────────────────────────────


CATALOGUE_RESOLVERS: tuple[CatalogueResolver, ...] = (
    CatalogueResolver(
        reference="zone_vulnerable_nitrates",
        label="Zone vulnérable nitrates (SIG)",
        description=(
            "Vrai si la parcelle est en zone vulnérable nitrates "
            "(résolution PostGIS sur les Maps SIG)."
        ),
        champ="en_zone_vulnerable",
        valeurs_branches=("True", "False"),
        resolve=_resolve_zone_vulnerable_nitrates,
    ),
    CatalogueResolver(
        reference="zone_note_5",
        label="Zone Note 5 (PACA, Occitanie, Sud-Ouest)",
        description=(
            "Vrai si la commune est en zone Sud-Ouest (régions PACA, "
            "Occitanie, départements 24/33/40/47/64). Résolu via le "
            "code INSEE."
        ),
        champ="zone_note_5",
        valeurs_branches=("True", "False"),
        resolve=_resolve_zone_note_5,
    ),
    CatalogueResolver(
        reference="zone_montagne_d113_14",
        label="Zone montagne D113-14 (bool)",
        description=(
            "Vrai si la commune est en zone montagne au sens D113-14, "
            "peu importe la note 6 vs 7. Résolu via le CSV juriste."
        ),
        champ="zone_montagne_d113_14",
        valeurs_branches=("True", "False"),
        resolve=_resolve_zone_montagne_d113_14,
    ),
    CatalogueResolver(
        reference="zonage_prairie_III",
        label="Zonage Prairie III (Note 7 pyrénées atl.)",
        description=(
            "Classification 3 valeurs pour les prairies de Type III, "
            "variante 'pyrénées atlantiques' (PACA + Occitanie + dept "
            "64). Valeurs : montagne_note_7 / montagne_note_6 / "
            "non_montagne."
        ),
        champ="zonage_prairie_III",
        valeurs_branches=("montagne_note_7", "montagne_note_6", "non_montagne"),
        resolve=_resolve_zonage_prairie_III,
    ),
    CatalogueResolver(
        reference="zone_note_7_montagne",
        label="Zone Note 7 montagne (variante élargie)",
        description=(
            "Classification 3 valeurs, variante 'élargie' (PACA + "
            "Occitanie OU 5 dept Sud-Ouest 24/33/40/47/64). Valeurs : "
            "montagne_note_7 / montagne_note_6 / non_montagne."
        ),
        champ="zonage_montagne_regional",
        valeurs_branches=("montagne_note_7", "montagne_note_6", "non_montagne"),
        resolve=_resolve_zone_note_7_montagne,
    ),
    CatalogueResolver(
        reference="zone_note_7_vs_note_6",
        label="Note 7 vs Note 6 (luzerne III IAA)",
        description=(
            "Utilisé après un filtre `zone_montagne_d113_14`. Tranche "
            "entre note_7 et note_6 (sans préfixe `montagne_`). "
            "Variante élargie."
        ),
        champ="zonage_montagne_regional",
        valeurs_branches=("note_7", "note_6"),
        resolve=_resolve_zone_note_7_vs_note_6,
    ),
)


_BY_REFERENCE: dict[str, CatalogueResolver] = {
    r.reference: r for r in CATALOGUE_RESOLVERS
}


def get_resolver(reference: str) -> CatalogueResolver | None:
    """Retourne le résolveur pour cette référence, ou None si inconnue."""
    return _BY_REFERENCE.get(reference)
