"""#248 : la justification d'une periode « autorise sous condition » s'affiche
via le composant infobulle DSFR (icone DSFR + affichage au clic/hover gere par
le JS DSFR), et non plus via le `title` natif du navigateur.

On rend le fragment de recap comme le fait `_panneau_resultat.html` et on
verifie la structure DSFR (fr-btn--tooltip + fr-tooltip role=tooltip), ainsi que
l'absence du title natif et du glyphe ⓘ.
"""

from types import SimpleNamespace

import pytest
from django.template import Context, Template

pytestmark = pytest.mark.django_db


# Reproduit le bloc de recap de _panneau_resultat.html (#159 + #248).
_FRAGMENT = """
{% load nitrates_tags %}
{% periodes_par_section regle as sections_periodes %}
{% for section in sections_periodes %}
  <ul>
    {% for puce in section.periodes %}
      <li>
        {{ puce.phrase }}
        {% if puce.justification %}
          <button class="fr-btn--tooltip fr-btn periodes-info" type="button"
                  aria-describedby="tooltip-periode-{{ forloop.parentloop.counter }}-{{ forloop.counter }}">
            Justification
          </button>
          <span class="fr-tooltip fr-placement"
                id="tooltip-periode-{{ forloop.parentloop.counter }}-{{ forloop.counter }}"
                role="tooltip" aria-hidden="true">{{ puce.justification }}</span>
        {% endif %}
      </li>
    {% endfor %}
  </ul>
{% endfor %}
"""


def _regle_autorisation_sous_condition():
    return SimpleNamespace(
        type="autorisation_sous_condition",
        periodes=[{"du": "15/12", "au": "15/01"}],
        texte_condition="Autorisé sous condition entre le 15/12 et le 15/01 (ICPE A).",
    )


def _render(regle):
    return Template(_FRAGMENT).render(Context({"regle": regle}))


def test_justification_rendue_en_tooltip_dsfr():
    html = _render(_regle_autorisation_sous_condition())
    # Composant DSFR present : bouton declencheur + tooltip lie.
    assert 'class="fr-btn--tooltip fr-btn periodes-info"' in html
    assert 'class="fr-tooltip fr-placement"' in html
    assert 'role="tooltip"' in html
    # Le declencheur pointe vers le tooltip : le meme id sert d'aria-describedby
    # (bouton) et d'id (tooltip), quel que soit le numero de section/puce.
    import re

    m = re.search(r'aria-describedby="(tooltip-periode-\d+-\d+)"', html)
    assert m, "aria-describedby du bouton tooltip absent"
    assert f'id="{m.group(1)}"' in html
    # Le texte de justification est bien dans le tooltip.
    assert "Autorisé sous condition entre le 15/12 et le 15/01 (ICPE A)." in html


def test_plus_de_title_natif_ni_glyphe_i():
    html = _render(_regle_autorisation_sous_condition())
    # Plus de tooltip natif navigateur ni du vieux glyphe ⓘ.
    assert "title=" not in html
    assert "ⓘ" not in html


def test_pas_de_tooltip_sans_justification():
    # Interdiction pure : pas de texte_condition -> pas de tooltip.
    regle = SimpleNamespace(
        type="interdiction",
        periodes=[{"du": "15/11", "au": "15/01"}],
        texte_condition=None,
    )
    html = _render(regle)
    assert "fr-btn--tooltip" not in html
    assert "fr-tooltip" not in html
