"""Fixtures partagees des tests nitrates."""

import pytest
import yaml as pyyaml
from django.utils import timezone

from envergo.nitrates.models import DecisionTree


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
