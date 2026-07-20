"""Fixtures partagees des tests nitrates."""

import pytest
import yaml as pyyaml
from django.core.management import call_command
from django.utils import timezone

from envergo.nitrates.models import DecisionTree


@pytest.fixture(scope="session", autouse=True)
def seed_referentiels_nitrates(django_db_setup, django_db_blocker):
    """Seed des tables referentiel dans la base de test.

    Depuis #226, `specs/referentiels.yaml` a ete supprime et la migration
    0012 (qui lisait ce YAML) est devenue no-op sur base neuve. La base de
    test (recreee from scratch par pytest-django) se retrouvait donc SANS
    aucun referentiel -> le resolveur `note_5` renvoyait vide et l'arbre
    prenait partout la branche `_autres` au lieu de `_note5`.

    On rejoue ici, une fois par session, la meme commande de seed que la CI
    lance en prod (`seed_referentiels`, idempotente via loaddata a clefs
    naturelles). La fixture `initial_referentiels.json` est la source de
    verite du seed depuis #226.
    """
    with django_db_blocker.unblock():
        call_command("seed_referentiels", verbosity=0)


@pytest.fixture
def make_active_tree(db):
    """Factory pour creer un DecisionTree actif depuis du YAML texte.

    Usage :
        def test_quelque_chose(make_active_tree):
            tree = make_active_tree(YAML_TEXTE)
    """

    def _make(yaml_text: str, name: str = "arbre_decision_national") -> DecisionTree:
        arbre = pyyaml.safe_load(yaml_text)
        # On supprime un eventuel actif existant pour eviter la contrainte
        # unique partielle. En test on veut un tree predictible par fixture.
        DecisionTree.objects.filter(status=DecisionTree.STATUS_ACTIVE).delete()
        return DecisionTree.objects.create(
            name=name,
            status=DecisionTree.STATUS_ACTIVE,
            contenu=arbre,
            contenu_yaml_brut=yaml_text,
            activated_at=timezone.now(),
        )

    return _make
