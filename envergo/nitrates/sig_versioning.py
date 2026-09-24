"""Bascule de millesime des couches SIG nitrates (ZV, ZAR).

Une couche SIG (`Map`) porte desormais un `version` (le millesime, ex
« 2026 ») et un `is_active`. Plusieurs millesimes d'une meme couche
coexistent en base, identifies par le meme `name` ; un seul est actif.

Pourquoi pas un simple remplacement en place : les couches SIG sont des
donnees reglementaires. Quand une DREAL republie un millesime, on veut
pouvoir basculer, comparer les deux etats et revenir en arriere sans
avoir detruit l'ancien. Un import qui ecrase ne le permet pas.

Le cycle de vie d'un import est donc :

    1. `get_or_create_millesime()` cree (ou retrouve) la Map du millesime
       cible, inactive. On la remplit tranquillement.
    2. `activer_millesime()` la rend active et desactive tous les autres
       millesimes de la meme couche, en une transaction.

Tant que l'etape 2 n'a pas eu lieu, le produit continue de servir
l'ancien millesime : un import interrompu ne casse rien.

Cote lecture, les requetes metier filtrent sur `map__is_active=True`
(cf. `envergo/nitrates/models.py` et `views.py`).
"""

import logging

from django.db import transaction

from envergo.geodata.models import Map

logger = logging.getLogger(__name__)


def get_or_create_millesime(
    *, name: str, version: str, defaults: dict | None = None
) -> tuple[Map, bool]:
    """Retourne (Map, created) pour le millesime `version` de la couche
    `name`.

    La Map est creee **inactive** : elle ne sera servie au produit qu'apres
    `activer_millesime()`. Rejouer un import sur un millesime deja importe
    reutilise la meme Map (idempotence).
    """
    defaults = dict(defaults or {})
    # `is_active` n'est jamais pilote par l'appelant : c'est
    # `activer_millesime` qui en a la responsabilite exclusive.
    defaults["is_active"] = False
    defaults["version"] = version

    existante = Map.objects.filter(name=name, version=version).first()
    if existante is not None:
        return existante, False

    # Adoption d'une couche pre-versioning. Une Map sans millesime existe
    # deja sur les environnements (creee par la migration nitrates 0002, ou
    # par un import anterieur au versioning) : on l'etiquette au lieu d'en
    # creer une seconde, sinon la couche serait servie en double.
    #
    # On ne fait cette adoption qu'UNE fois, pour le premier millesime
    # importe ; les suivants creent bien une nouvelle Map.
    orpheline = Map.objects.filter(name=name, version="").first()
    if orpheline is not None:
        orpheline.version = version
        orpheline.is_active = False
        orpheline.save(update_fields=["version", "is_active"])
        return orpheline, False

    map_obj = Map.objects.create(name=name, **defaults)
    return map_obj, True


@transaction.atomic
def activer_millesime(map_obj: Map) -> list[Map]:
    """Active `map_obj` et desactive les autres millesimes de la couche.

    Retourne la liste des Map desactivees (pour le log / le rapport de la
    commande). Les zones des millesimes desactives ne sont PAS supprimees :
    c'est ce qui rend le rollback instantane
    (cf. `reactiver_millesime`).
    """
    anciens = list(
        Map.objects.filter(name=map_obj.name, is_active=True).exclude(pk=map_obj.pk)
    )
    Map.objects.filter(name=map_obj.name, is_active=True).exclude(pk=map_obj.pk).update(
        is_active=False
    )

    map_obj.is_active = True
    map_obj.save(update_fields=["is_active"])

    logger.info(
        "Millesime actif pour %s : %s (desactives : %s)",
        map_obj.name,
        map_obj.version,
        ", ".join(m.version or "—" for m in anciens) or "aucun",
    )
    return anciens


@transaction.atomic
def reactiver_millesime(*, name: str, version: str) -> Map:
    """Rollback : reactive un millesime anterieur, desactive les autres.

    Ne re-importe rien — les zones de l'ancien millesime sont restees en
    base. C'est une bascule de pointeur, instantanee.
    """
    try:
        cible = Map.objects.get(name=name, version=version)
    except Map.DoesNotExist:
        millesimes = list(
            Map.objects.filter(name=name)
            .order_by("version")
            .values_list("version", flat=True)
        )
        raise ValueError(
            f"Millesime « {version} » inconnu pour la couche « {name} ». "
            f"Millesimes en base : {millesimes or 'aucun'}."
        )

    activer_millesime(cible)
    return cible


def lister_millesimes(name: str | None = None):
    """Etat des millesimes en base, pour les commandes de diagnostic."""
    qs = Map.objects.all()
    if name:
        qs = qs.filter(name=name)
    return qs.order_by("name", "version")


def purger_millesime(*, name: str, version: str) -> tuple[Map, int]:
    """Supprime definitivement un millesime (et ses zones).

    A n'utiliser que pour faire de la place, une fois qu'un millesime est
    valide depuis longtemps. Refuse de supprimer le millesime actif : on ne
    peut pas se retrouver sans couche servie par accident.
    """
    try:
        cible = Map.objects.get(name=name, version=version)
    except Map.DoesNotExist:
        raise ValueError(f"Millesime « {version} » inconnu pour « {name} ».")

    if cible.is_active:
        raise ValueError(
            f"Le millesime « {version} » de « {name} » est ACTIF : "
            "bascule d'abord sur un autre millesime avant de le purger."
        )

    nb_zones = cible.zones.count()
    cible.delete()
    return cible, nb_zones
