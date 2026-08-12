"""Tests du filtre |glossaire (linkification des termes définis, carte #110)."""

import pytest
from django.template import Context, Template

from envergo.nitrates.contenu_rich.glossaire import invalider_cache_glossaire
from envergo.nitrates.models import ContenuRichDSFR
from envergo.nitrates.models_contenu_rich import TYPE_DEFINITION
from envergo.nitrates.templatetags.nitrates_tags import glossaire

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _cache_glossaire_propre():
    invalider_cache_glossaire()
    yield
    invalider_cache_glossaire()


def _definition(cle, titre, termes=None):
    return ContenuRichDSFR.objects.create(
        cle=cle,
        libelle_admin=titre,
        type_contenu=TYPE_DEFINITION,
        titre_public=titre,
        termes_declencheurs=termes or [],
    )


@pytest.fixture
def glossaire_interculture():
    _definition("definition.interculture", "Interculture")
    _definition("definition.interculture-longue", "Interculture longue")
    _definition("definition.azote-efficace", "Azote efficace")
    _definition("definition.c-n", "C / N", termes=["C/N", "rapport C/N"])
    invalider_cache_glossaire()


def test_glossaire_vide_texte_echappe_tel_quel():
    html = glossaire("Une <b>question</b> sans glossaire")
    assert html == "Une &lt;b&gt;question&lt;/b&gt; sans glossaire"


def test_terme_wrappe_en_lien(glossaire_interculture):
    html = glossaire("Pendant l'interculture, le sol est nu.")
    assert (
        '<a class="def-terme" data-def-cle="definition.interculture" '
        'href="/definitions/#interculture">interculture</a>' in html
    )


def test_longest_match_prime(glossaire_interculture):
    html = glossaire("En interculture longue uniquement.")
    assert 'data-def-cle="definition.interculture-longue"' in html
    # Le match court ne doit pas découper le long.
    assert html.count("<a ") == 1
    assert ">interculture longue</a>" in html


def test_insensible_a_la_casse(glossaire_interculture):
    html = glossaire("Interculture : période entre deux cultures.")
    # La casse du texte source est préservée dans le libellé du lien.
    assert ">Interculture</a>" in html


def test_frontiere_accentuee_pas_de_sous_mot(glossaire_interculture):
    # « azote efficacement » ne doit PAS matcher « azote efficace » : la
    # frontière lookahead (?!\w) tient compte des lettres accentuées comme
    # des lettres normales.
    html = glossaire("L'azote efficacement absorbé.")
    assert "<a " not in html
    # Mais le vrai terme matche, y compris précédé d'une apostrophe.
    html2 = glossaire("La part d'azote efficace apportée.")
    assert ">azote efficace</a>" in html2


def test_xss_texte_source_echappe(glossaire_interculture):
    html = glossaire('<script>alert("interculture")</script>')
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    # Le terme entre guillemets dans le JS échappé est quand même wrappé sans
    # casser l'échappement.
    assert "&quot;" in html


def test_variante_avec_slash(glossaire_interculture):
    html = glossaire("Le rapport C/N conditionne le type.")
    assert 'data-def-cle="definition.c-n"' in html
    assert ">rapport C/N</a>" in html


def test_texte_avec_esperluette_adjacente(glossaire_interculture):
    # Une entité issue de l'échappement (&amp;) ne doit pas empêcher ni
    # corrompre le match voisin.
    html = glossaire("Azote efficace & C/N")
    assert ">Azote efficace</a>" in html
    assert "&amp;" in html
    assert ">C/N</a>" in html


def test_rendu_dans_un_template(glossaire_interculture):
    # Usage réel : {{ q.texte|glossaire }} — la sortie est marquée safe (pas
    # de double échappement par l'auto-escape du template).
    tpl = Template("{% load nitrates_tags %}<p>{{ texte|glossaire }}</p>")
    html = tpl.render(Context({"texte": "Quelle interculture ?"}))
    assert '<a class="def-terme"' in html
    assert "&lt;a" not in html


def test_none_rend_chaine_vide(glossaire_interculture):
    assert glossaire(None) == ""
