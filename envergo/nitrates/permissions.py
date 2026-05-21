"""Helpers de permissions pour l'admin nitrates.

Centralise les regles d'acces qui depassent ce que Django Group offre :
  - ownership (le user n'edite que ses propres drafts)
  - verrou arbre actif (personne dans `external_observator` ne touche
    a l'arbre actif)
  - restriction visuelle a l'app `nitrates` dans l'admin

Le groupe `external_observator` est cree par la migration
0010_external_observator_group.
"""

EXTERNAL_OBSERVATOR_GROUP = "external_observator"


def is_external_observator(user) -> bool:
    """True si l'utilisateur appartient au groupe external_observator
    ET n'est pas superuser (un superuser bypass les restrictions)."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return False
    return user.groups.filter(name=EXTERNAL_OBSERVATOR_GROUP).exists()


def can_change_tree(user, tree) -> bool:
    """True si l'utilisateur peut editer ce DecisionTree.

    Regles :
      - superuser : toujours OK
      - external_observator :
          * arbre actif : non
          * arbre archive : non (clone seulement)
          * arbre draft : oui si created_by == user
      - autres staff (intras) : OK sur draft + actif (regles existantes)
    """
    if not user or not user.is_authenticated or not user.is_staff:
        return False
    if user.is_superuser:
        return True
    if is_external_observator(user):
        # Import differé pour éviter le cycle avec models.py
        from envergo.nitrates.models import DecisionTree

        if tree.status != DecisionTree.STATUS_DRAFT:
            return False
        return tree.created_by_id == user.pk
    # Staff intra non-superuser : on garde le comportement actuel
    # (acces large via has_change_permission Django standard).
    return True


def can_delete_tree(user, tree) -> bool:
    """True si l'utilisateur peut supprimer ce DecisionTree.

    Regles :
      - superuser : toujours OK
      - external_observator : uniquement ses propres drafts
      - autres staff : OK
    """
    if not user or not user.is_authenticated or not user.is_staff:
        return False
    if user.is_superuser:
        return True
    if is_external_observator(user):
        from envergo.nitrates.models import DecisionTree

        if tree.status != DecisionTree.STATUS_DRAFT:
            return False
        return tree.created_by_id == user.pk
    return True


def can_activate_tree(user, tree) -> bool:
    """True si l'utilisateur peut activer ce DecisionTree (passer draft
    en active). Reserve aux superusers et intras non-observator."""
    if not user or not user.is_authenticated or not user.is_staff:
        return False
    if user.is_superuser:
        return True
    if is_external_observator(user):
        return False
    return True


def can_preview_tree(user, tree) -> bool:
    """True si l'utilisateur peut prévisualiser ce tree via le simulateur
    avec `?draft_tree_id=<pk>` (cf. killer feature #80 - issue close).

    Règles :
      - non-staff : non (le simulateur public ne doit voir que l'actif)
      - superuser : oui sur tout draft / actif / archive
      - intra (staff non-observator) : oui sur tout
      - external_observator : oui uniquement sur ses propres drafts
    """
    if not user or not user.is_authenticated or not user.is_staff:
        return False
    if user.is_superuser:
        return True
    if is_external_observator(user):
        from envergo.nitrates.models import DecisionTree

        if tree.status != DecisionTree.STATUS_DRAFT:
            return False
        return tree.created_by_id == user.pk
    return True


def can_edit_active(user) -> bool:
    """True si l'utilisateur peut declencher l'edition de l'arbre actif
    (= creation d'un draft a partir de l'actif, qui sera ensuite active).
    Interdit aux observateurs externes."""
    if not user or not user.is_authenticated or not user.is_staff:
        return False
    if user.is_superuser:
        return True
    if is_external_observator(user):
        return False
    return True
