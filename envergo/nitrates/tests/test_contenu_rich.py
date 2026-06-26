"""Tests du contenu riche éditable DSFR (carte #131)."""

import pytest
from django.core.management import call_command

from envergo.nitrates.contenu_rich.compilateur import compile_dsfr
from envergo.nitrates.models import ContenuRichDSFR

# ─── Compilateur (pur, sans DB) ──────────────────────────────────────────────


def test_titre_principal():
    html = compile_dsfr([{"type": "titre_principal", "data": {"texte": "Titre"}}])
    assert "<h3" in html and "Titre</h3>" in html


def test_titre_paragraphe_est_un_h6():
    html = compile_dsfr(
        [{"type": "titre_paragraphe", "data": {"texte": "Le principe"}}]
    )
    # Sous-titre = H6 DSFR (demande Coralie, commentaires Notion #136).
    assert '<h6 class="fr-h6">Le principe</h6>' in html


def test_paragraphe():
    html = compile_dsfr([{"type": "paragraphe", "data": {"texte": "Bonjour"}}])
    assert "<p>Bonjour</p>" in html


def test_gras_inline_segments():
    # Texte = liste de segments {texte, gras} (carte #136) -> <strong> ciblé.
    html = compile_dsfr(
        [
            {
                "type": "paragraphe",
                "data": {
                    "texte": [
                        {"texte": "La dose est de "},
                        {"texte": "100 kg", "gras": True},
                        {"texte": " par hectare."},
                    ]
                },
            }
        ]
    )
    assert "<p>La dose est de <strong>100 kg</strong> par hectare.</p>" in html


def test_gras_inline_echappement_preserve():
    # Le gras ne doit PAS ouvrir une faille : le contenu d'un segment gras
    # reste échappé (seul <strong> est introduit par le compilateur).
    html = compile_dsfr(
        [
            {
                "type": "paragraphe",
                "data": {"texte": [{"texte": "<script>", "gras": True}]},
            }
        ]
    )
    assert "<strong>&lt;script&gt;</strong>" in html
    assert "<script>" not in html


def test_gras_inline_dans_liste():
    html = compile_dsfr(
        [
            {
                "type": "liste",
                "data": {
                    "items": [
                        {"texte": [{"texte": "gras", "gras": True}]},
                        {"texte": "plat"},
                    ]
                },
            }
        ]
    )
    assert "<li><strong>gras</strong></li>" in html
    assert "<li>plat</li>" in html


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


def test_id_accordion_prefixe_par_zone():
    # Le préfixe d'id distingue chaque zone -> deux zones rendues sur la même
    # page ne partagent PAS les mêmes id d'accordéon (carte #157).
    blocs = [{"type": "foldable", "data": {"titre": "Suivi", "blocs": []}}]
    html_a = compile_dsfr(blocs, id_prefix="cr-zone-a")
    html_b = compile_dsfr(blocs, id_prefix="cr-zone-b")
    assert 'id="cr-zone-a-accordion-1"' in html_a
    assert 'id="cr-zone-b-accordion-1"' in html_b
    # Concaténées (comme sur la page résultat), aucun id n'est dupliqué.
    page = html_a + html_b
    assert page.count('id="cr-zone-a-accordion-1"') == 1
    assert page.count('id="cr-zone-b-accordion-1"') == 1
    # Le bouton de chaque zone pilote bien SON propre collapse.
    assert 'aria-controls="cr-zone-a-accordion-1"' in html_a
    assert 'aria-controls="cr-zone-b-accordion-1"' in html_b


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
    assert "<p>ok</p>" in html


def test_enveloppe_schema_toleree():
    # compile_dsfr accepte {"schema": N, "blocs": [...]} aussi bien qu'une liste.
    html = compile_dsfr(
        {"schema": 1, "blocs": [{"type": "paragraphe", "data": {"texte": "ok"}}]}
    )
    assert "<p>ok</p>" in html


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


# ─── Prescriptions conditionnées (PC, carte #136) ────────────────────────────


@pytest.mark.django_db
def test_seed_cree_les_pc_par_cle_convention():
    # Le contenu riche des PC est porté par le champ `blocs` de CodePrescription
    # (carte #136), pas par un ContenuRichDSFR. Le seed referentiels le remplit.
    from envergo.nitrates.models import CodePrescription

    call_command("seed_referentiels")
    for ident in ("pc1", "pc2", "pc16"):
        pc = CodePrescription.objects.get(identifiant=ident)
        assert pc.blocs.get("blocs"), ident
        # texte legacy préservé (fallback, non cassant).
        assert pc.texte_court


@pytest.mark.django_db
def test_pc_blocs_compile_avec_foldable_suivi():
    # PC2 a une section dépliable « Précisions sur le suivi » (cf. maquette).
    from envergo.nitrates.models import CodePrescription

    call_command("seed_referentiels")
    pc = CodePrescription.objects.get(identifiant="pc2")
    html = compile_dsfr(pc.blocs)
    assert "Conditions à respecter" in html  # titre principal
    assert 'class="fr-h6"' in html  # sous-titres H6 (Le principe…)
    assert "Précisions sur le suivi" in html  # foldable
    assert 'class="fr-accordion"' in html


@pytest.mark.django_db
def test_pc_sans_blocs_compile_vide():
    # Un PC sans blocs -> compile_dsfr rend "" : le template retombe alors sur
    # le texte legacy (fallback, transition 2 temps).
    from envergo.nitrates.models import CodePrescription

    pc = CodePrescription.objects.create(
        identifiant="pcZ", texte_court="legacy", blocs={}
    )
    assert compile_dsfr(pc.blocs) == ""


@pytest.mark.django_db
def test_seed_referentiels_n_ecrase_pas_blocs_existants():
    # Re-seed ne doit pas écraser un contenu riche édité dans l'admin.
    from envergo.nitrates.models import CodePrescription

    call_command("seed_referentiels")
    pc = CodePrescription.objects.get(identifiant="pc1")
    pc.blocs = {
        "schema": 1,
        "blocs": [{"type": "paragraphe", "data": {"texte": "EDIT"}}],
    }
    pc.save(update_fields=["blocs"])
    call_command("seed_referentiels")
    pc.refresh_from_db()
    assert pc.blocs["blocs"][0]["data"]["texte"] == "EDIT"


# ─── Indentation des blocs (carte #136) ──────────────────────────────────────


def test_indent_applique_marge():
    html = compile_dsfr(
        [
            {"type": "paragraphe", "data": {"texte": "normal"}},
            {"type": "paragraphe", "data": {"texte": "decale", "indent": 2}},
        ]
    )
    assert "<p>normal</p>" in html
    # bloc indenté enveloppé dans une marge gauche (2 niveaux * 1.5rem).
    assert "margin-left:3.0rem" in html or "margin-left:3rem" in html


def test_indent_zero_pas_de_wrapper():
    html = compile_dsfr([{"type": "paragraphe", "data": {"texte": "x", "indent": 0}}])
    # Pas de wrapper d'INDENTATION (margin-left) quand indent=0. Le conteneur
    # .contenu-rich global, lui, est toujours présent.
    assert "<p>x</p>" in html
    assert "margin-left" not in html


def test_indent_borne():
    # indent délirant borné (pas de marge absurde / négative).
    html = compile_dsfr([{"type": "paragraphe", "data": {"texte": "x", "indent": 99}}])
    assert "margin-left:9.0rem" in html or "margin-left:9rem" in html
