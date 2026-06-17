"""Tests du contenu riche éditable DSFR (carte #131)."""

import pytest
from django.core.management import call_command

from envergo.nitrates.contenu_rich.compilateur import compile_dsfr
from envergo.nitrates.models import ContenuRichDSFR

# ─── Compilateur (pur, sans DB) ──────────────────────────────────────────────


def test_titre_principal():
    html = compile_dsfr([{"type": "titre_principal", "data": {"texte": "Titre"}}])
    assert "<h3" in html and "Titre</h3>" in html


def test_titre_paragraphe_est_gras_pas_un_titre():
    html = compile_dsfr(
        [{"type": "titre_paragraphe", "data": {"texte": "Le principe"}}]
    )
    # Sous-titre = paragraphe gras DSFR (ne casse pas la hiérarchie a11y).
    assert 'class="fr-text--bold"' in html
    assert "Le principe" in html


def test_paragraphe():
    html = compile_dsfr([{"type": "paragraphe", "data": {"texte": "Bonjour"}}])
    assert html == "<p>Bonjour</p>"


def test_liste_simple():
    html = compile_dsfr(
        [{"type": "liste", "data": {"items": [{"texte": "a"}, {"texte": "b"}]}}]
    )
    assert html.count("<li>") == 2
    assert "<li>a</li>" in html and "<li>b</li>" in html


def test_liste_indentee_multi_niveaux():
    html = compile_dsfr(
        [
            {
                "type": "liste",
                "data": {
                    "items": [
                        {"texte": "parent", "enfants": [{"texte": "enfant"}]},
                    ]
                },
            }
        ]
    )
    # La sous-puce est une <ul> imbriquée dans le <li> parent.
    assert "<li>parent<ul><li>enfant</li></ul></li>" in html


def test_citation_callout():
    html = compile_dsfr([{"type": "citation", "data": {"texte": "Surface ÷ 20"}}])
    assert 'class="fr-callout"' in html
    assert "Surface ÷ 20" in html


def test_foldable_accordion():
    html = compile_dsfr(
        [
            {
                "type": "foldable",
                "data": {
                    "titre": "Précisions",
                    "blocs": [{"type": "paragraphe", "data": {"texte": "corps"}}],
                },
            }
        ]
    )
    assert 'class="fr-accordion"' in html
    assert 'class="fr-collapse"' in html
    assert "Précisions" in html
    assert "<p>corps</p>" in html


def test_foldable_imbrication_incremente_le_niveau_de_titre():
    html = compile_dsfr(
        [
            {
                "type": "foldable",
                "data": {
                    "titre": "Section",
                    "blocs": [{"type": "titre_principal", "data": {"texte": "Sous"}}],
                },
            }
        ],
        niveau_base=3,
    )
    # foldable rendu en h3, son titre_principal enfant descend en h4.
    assert "<h4" in html


def test_id_accordion_uniques():
    html = compile_dsfr(
        [
            {"type": "foldable", "data": {"titre": "A", "blocs": []}},
            {"type": "foldable", "data": {"titre": "B", "blocs": []}},
        ]
    )
    assert "contenu-rich-accordion-1" in html
    assert "contenu-rich-accordion-2" in html


def test_echappement_html_anti_injection():
    html = compile_dsfr(
        [
            {
                "type": "paragraphe",
                "data": {"texte": '<script>alert("x")</script> & <b>'},
            }
        ]
    )
    # Aucune balise saisie ne survit : tout est échappé.
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&amp;" in html


def test_type_inconnu_ignore_silencieusement():
    html = compile_dsfr(
        [
            {"type": "type_qui_nexiste_pas", "data": {"texte": "x"}},
            {"type": "paragraphe", "data": {"texte": "ok"}},
        ]
    )
    assert html == "<p>ok</p>"


def test_enveloppe_schema_toleree():
    # compile_dsfr accepte {"schema": N, "blocs": [...]} aussi bien qu'une liste.
    html = compile_dsfr(
        {"schema": 1, "blocs": [{"type": "paragraphe", "data": {"texte": "ok"}}]}
    )
    assert html == "<p>ok</p>"


# ─── Modèle + seed (DB) ──────────────────────────────────────────────────────

pytestmark_db = pytest.mark.django_db


@pytest.mark.django_db
def test_cle_unique():
    ContenuRichDSFR.objects.create(cle="a.b", libelle_admin="A")
    with pytest.raises(Exception):
        ContenuRichDSFR.objects.create(cle="a.b", libelle_admin="A bis")


@pytest.mark.django_db
def test_liste_blocs_property_tolerante():
    c = ContenuRichDSFR.objects.create(
        cle="x.y",
        libelle_admin="X",
        blocs={"schema": 1, "blocs": [{"type": "paragraphe", "data": {}}]},
    )
    assert len(c.liste_blocs) == 1
    # Forme liste nue
    c.blocs = [{"type": "paragraphe", "data": {}}]
    assert len(c.liste_blocs) == 1
    # Dict vide (default)
    c.blocs = {}
    assert c.liste_blocs == []


@pytest.mark.django_db
def test_seed_idempotent():
    call_command("seed_contenus_rich")
    n1 = ContenuRichDSFR.objects.count()
    assert ContenuRichDSFR.objects.filter(cle="resultat.regles_permanentes").exists()
    # 2e passage : aucun nouveau créé.
    call_command("seed_contenus_rich")
    assert ContenuRichDSFR.objects.count() == n1


@pytest.mark.django_db
def test_seed_contenu_compile_selon_maquette():
    # Contenu de départ calé sur la maquette (Frame 35) : titre + intro + 4
    # sections dépliables (Cours d'eau, Sols en forte pente, etc.).
    call_command("seed_contenus_rich")
    obj = ContenuRichDSFR.objects.get(cle="resultat.regles_permanentes")
    html = compile_dsfr(obj.liste_blocs)
    # Titre + intro hors accordéon.
    assert "Règles permanentes" in html
    assert "Ces règles s" in html
    # 4 sections dépliables DSFR.
    assert html.count('class="fr-accordion"') == 4
    for titre in (
        "Cours d",
        "Sols en forte pente",
        "Sols détrempés et inondés",
        "Sols enneigés et gelés",
    ):
        assert titre in html
