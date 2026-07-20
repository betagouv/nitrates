"""Tests des commandes de dump GitOps (carte #50).

`dump_active_trees` (arbres) et `dump_referentiels` (référentiels) sont le
pendant miroir de `import_decision_tree` / `seed_referentiels` : la DB active
est dumpée dans des fichiers canoniques versionnés (repo = source de vérité).

Valide les propriétés qui font tenir le GitOps :
  - nommage canonique déduit de la seule identité (scope, région)
  - round-trip stable : dump puis --check passe (idempotent)
  - --check échoue si le fichier du repo diverge de la DB active
  - référentiels dumpés en CLÉS NATURELLES (portabilité inter-DB : pas de PK)
  - ContenuRichDSFR présent dans le dump référentiels (correctif nat-key #50)
"""

import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from envergo.nitrates.management.commands.dump_active_trees import canonical_filename
from envergo.nitrates.management.commands.validate_arbres_actifs import (
    scope_from_filename,
)
from envergo.nitrates.models import DecisionTree
from envergo.nitrates.tests.test_import_decision_tree import ARBRE_VALIDE_YAML

pytestmark = pytest.mark.django_db


# ─── dump_active_trees ────────────────────────────────────────────────────────


def test_canonical_filename_identite_scope_region():
    """L'identité d'un arbre = (scope, région) uniquement. Pas le nom."""
    assert canonical_filename(DecisionTree.SCOPE_NATIONAL, "") == "national.yaml"
    assert canonical_filename(DecisionTree.SCOPE_REGION, "44") == "region_44.yaml"
    assert canonical_filename(DecisionTree.SCOPE_REGION, "32") == "region_32.yaml"
    assert canonical_filename(DecisionTree.SCOPE_ZAR, "44") == "zar_44.yaml"


def _make_active_tree(name="pan_v1"):
    """Crée un arbre national actif directement en base (sans import/validation).

    Le test de dump n'a besoin que d'un arbre actif avec un `contenu` dict ; on
    évite la validation d'import (hors périmètre du dump).
    """
    contenu = {"meta": {"version": "1"}, "racine": {"type": "resultat"}}
    tree = DecisionTree.objects.create(
        name=name,
        status=DecisionTree.STATUS_DRAFT,
        scope=DecisionTree.SCOPE_NATIONAL,
        contenu=contenu,
    )
    tree.activate()
    return tree


def test_dump_active_trees_ecrit_puis_check_passe(tmp_path):
    """Après un dump, --check passe (round-trip idempotent)."""
    _make_active_tree()
    specs = tmp_path / "specs"

    out = StringIO()
    call_command("dump_active_trees", dir=str(specs), stdout=out, stderr=StringIO())
    canon = specs / "arbres_actifs" / "national.yaml"
    assert canon.exists(), "le fichier canonique national.yaml doit être écrit"

    # --check ne doit rien lever maintenant que le fichier reflète la DB.
    call_command(
        "dump_active_trees",
        dir=str(specs),
        check=True,
        stdout=StringIO(),
        stderr=StringIO(),
    )


def test_dump_active_trees_check_echoue_si_perime(tmp_path):
    """--check lève si le fichier du repo diverge de la DB active."""
    _make_active_tree()
    specs = tmp_path / "specs"
    call_command(
        "dump_active_trees", dir=str(specs), stdout=StringIO(), stderr=StringIO()
    )

    # On corrompt le fichier canonique → --check doit échouer.
    canon = specs / "arbres_actifs" / "national.yaml"
    canon.write_text("meta:\n  version: 'perime'\n", encoding="utf-8")
    with pytest.raises(CommandError):
        call_command(
            "dump_active_trees",
            dir=str(specs),
            check=True,
            stdout=StringIO(),
            stderr=StringIO(),
        )


def test_dump_active_trees_check_echoue_si_absent(tmp_path):
    """--check lève si le fichier canonique n'existe pas encore."""
    _make_active_tree()
    specs = tmp_path / "specs"  # jamais dumpé
    with pytest.raises(CommandError):
        call_command(
            "dump_active_trees",
            dir=str(specs),
            check=True,
            stdout=StringIO(),
            stderr=StringIO(),
        )


# ─── validate_arbres_actifs (déduction scope + garde-fou CI) ─────────────────


def test_scope_from_filename_deduit_identite():
    """Le scope se déduit du seul nom de fichier canonique (inverse du dump)."""
    assert scope_from_filename("national.yaml") == (DecisionTree.SCOPE_NATIONAL, "")
    assert scope_from_filename("region_44.yaml") == (DecisionTree.SCOPE_REGION, "44")
    assert scope_from_filename("zar_44.yaml") == (DecisionTree.SCOPE_ZAR, "44")
    # Hors convention -> None (le garde-fou CI le refusera).
    assert scope_from_filename("nawak.yaml") is None


def test_validate_arbres_actifs_refuse_yaml_casse(tmp_path):
    """Un YAML canonique cassé fait échouer le garde-fou CI."""
    arbres = tmp_path / "arbres_actifs"
    arbres.mkdir()
    (arbres / "national.yaml").write_text(
        "{ ceci n'est pas: du: yaml valide", encoding="utf-8"
    )
    with pytest.raises(CommandError):
        call_command("validate_arbres_actifs", dir=str(tmp_path), stdout=StringIO())


# ─── load_arbres_actifs (reload CD : draft->active, jamais override) ─────────
#
# Le reload passe par import_decision_tree qui VALIDE l'arbre (referentiels +
# scope) : on part donc d'un arbre réellement valide (ARBRE_VALIDE_YAML), pas
# du fixture minimal des tests de dump.


def _make_active_national_valide(settings, tmp_path):
    """Importe l'arbre national valide en actif, retourne le tree."""
    settings.NITRATES_SPECS_DIR = str(tmp_path)
    src = tmp_path / "src.yaml"
    src.write_text(ARBRE_VALIDE_YAML, encoding="utf-8")
    call_command(
        "import_decision_tree", str(src), mode="force-active", name="pan_v1",
        stdout=StringIO(), stderr=StringIO(),
    )
    return DecisionTree.objects.get(
        scope=DecisionTree.SCOPE_NATIONAL, status=DecisionTree.STATUS_ACTIVE
    )


def test_load_arbres_actifs_cree_nouvelle_version_active(settings, tmp_path):
    """Reload d'un arbre canonique -> nouvelle version active, ancienne archivée.

    Le CD se comporte comme un éditeur humain : jamais d'UPDATE in-place.
    """
    ancien = _make_active_national_valide(settings, tmp_path)
    specs = tmp_path / "specs"
    call_command(
        "dump_active_trees", dir=str(specs), stdout=StringIO(), stderr=StringIO()
    )

    call_command(
        "load_arbres_actifs",
        dir=str(specs),
        only="national",
        stdout=StringIO(),
        stderr=StringIO(),
    )

    actifs = DecisionTree.objects.filter(
        scope=DecisionTree.SCOPE_NATIONAL, status=DecisionTree.STATUS_ACTIVE
    )
    assert actifs.count() == 1, "un seul actif par zone"
    nouvel_actif = actifs.first()
    assert nouvel_actif.pk != ancien.pk, "une NOUVELLE version, pas un override"
    ancien.refresh_from_db()
    assert ancien.status == DecisionTree.STATUS_ARCHIVE, "l'ancien passe en archive"


def test_load_arbres_actifs_skip_si_identique(settings, tmp_path):
    """--skip-si-identique ne recharge pas un arbre inchangé (pas de doublon)."""
    _make_active_national_valide(settings, tmp_path)
    specs = tmp_path / "specs"
    call_command(
        "dump_active_trees", dir=str(specs), stdout=StringIO(), stderr=StringIO()
    )

    avant = DecisionTree.objects.filter(scope=DecisionTree.SCOPE_NATIONAL).count()
    call_command(
        "load_arbres_actifs",
        dir=str(specs),
        skip_si_identique=True,
        stdout=StringIO(),
        stderr=StringIO(),
    )
    apres = DecisionTree.objects.filter(scope=DecisionTree.SCOPE_NATIONAL).count()
    assert apres == avant, "aucune version créée si le contenu est identique"


# ─── dump_referentiels ────────────────────────────────────────────────────────


def test_dump_referentiels_cles_naturelles(tmp_path):
    """Le dump référentiels serialise en clés naturelles, pas en PK.

    Condition de portabilité inter-DB : aucun objet ne porte de `pk` explicite,
    et les FK sont des listes (clé naturelle), pas des entiers.
    """
    call_command("seed_referentiels", stdout=StringIO(), stderr=StringIO())
    fixture = tmp_path / "refs.json"
    call_command("dump_referentiels", fixture=str(fixture), stdout=StringIO())

    data = json.loads(fixture.read_text(encoding="utf-8"))
    assert data, "le dump ne doit pas être vide"
    assert all(o.get("pk") is None for o in data), "aucune PK explicite (nat-key)"

    # Vraies FK (par modèle) sérialisées en liste (clé naturelle), jamais en int.
    # NB: Fertilisant.categorie est un CharField (choices), pas une FK -> exclu.
    fk_by_model = {
        "nitrates.culture": ("categorie", "branche_culturale"),
        "nitrates.codeprescription": ("note_reglementaire",),
    }
    for o in data:
        for f in fk_by_model.get(o["model"], ()):
            val = o["fields"].get(f)
            if val is not None:
                assert isinstance(
                    val, list
                ), f"{o['model']}.{f} doit être une clé naturelle"


def test_dump_referentiels_inclut_contenu_rich(tmp_path):
    """ContenuRichDSFR est dans le dump (correctif mixin nat-key #50)."""
    call_command("seed_referentiels", stdout=StringIO(), stderr=StringIO())
    fixture = tmp_path / "refs.json"
    call_command("dump_referentiels", fixture=str(fixture), stdout=StringIO())
    data = json.loads(fixture.read_text(encoding="utf-8"))
    modeles = {o["model"] for o in data}
    assert "nitrates.contenurichdsfr" in modeles


def test_dump_referentiels_check_idempotent(tmp_path):
    """Après un dump, --check passe (fixture == DB)."""
    call_command("seed_referentiels", stdout=StringIO(), stderr=StringIO())
    fixture = tmp_path / "refs.json"
    call_command("dump_referentiels", fixture=str(fixture), stdout=StringIO())
    call_command(
        "dump_referentiels", fixture=str(fixture), check=True, stdout=StringIO()
    )
