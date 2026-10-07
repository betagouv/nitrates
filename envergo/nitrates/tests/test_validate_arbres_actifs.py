"""Tests de la commande `validate_arbres_actifs` (garde-fou CI GitOps #50)."""

import textwrap

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from envergo.nitrates.management.commands import validate_arbres_actifs

pytestmark = pytest.mark.django_db

ARBRE_VALIDE_YAML = textwrap.dedent(
    """\
    metadata:
      version: "0.0.1-test"
    arbre:
      noeud:
        type_noeud: "catalogue"
        id: "n_zvn"
        champ: "en_zone_vulnerable"
        source: "sig"
        reference: "zone_vulnerable_nitrates"
        branches:
          - valeur: false
            regle:
              id: "r_hors_zvn"
              type: "non_applicable"
              message: "ZV non concernee."
          - valeur: true
            regle:
              id: "r_en_zvn"
              type: "non_applicable"
              message: "Reglementation nitrates applicable."
    """
)

ARBRE_INVALIDE_YAML = "metadata:\n  version: broken\n"


def test_sans_repertoire_arbres_actifs_rien_a_valider(tmp_path, capsys):
    call_command("validate_arbres_actifs", "--dir", str(tmp_path))
    assert "rien à valider" in capsys.readouterr().out


def test_repertoire_vide_signale_aucun_fichier(tmp_path, capsys):
    (tmp_path / "arbres_actifs").mkdir()
    call_command("validate_arbres_actifs", "--dir", str(tmp_path))
    assert "Aucun fichier .yaml" in capsys.readouterr().out


def test_nom_hors_convention_est_une_erreur(tmp_path):
    arbres_dir = tmp_path / "arbres_actifs"
    arbres_dir.mkdir()
    (arbres_dir / "fichier_bizarre.yaml").write_text(
        ARBRE_VALIDE_YAML, encoding="utf-8"
    )
    with pytest.raises(CommandError, match="hors convention"):
        call_command("validate_arbres_actifs", "--dir", str(tmp_path))


def test_yaml_invalide_est_signale(tmp_path):
    arbres_dir = tmp_path / "arbres_actifs"
    arbres_dir.mkdir()
    (arbres_dir / "national.yaml").write_text("clef: [non fermé", encoding="utf-8")
    with pytest.raises(CommandError, match="YAML invalide"):
        call_command("validate_arbres_actifs", "--dir", str(tmp_path))


def test_arbre_structurellement_invalide_est_signale(tmp_path):
    arbres_dir = tmp_path / "arbres_actifs"
    arbres_dir.mkdir()
    (arbres_dir / "national.yaml").write_text(ARBRE_INVALIDE_YAML, encoding="utf-8")
    with pytest.raises(CommandError, match="national.yaml"):
        call_command("validate_arbres_actifs", "--dir", str(tmp_path))


def test_referentiels_absents_n_empeche_pas_la_validation(tmp_path, monkeypatch):
    """Si `load_referentiels` lève `FileNotFoundError` (specs incomplets),
    on valide quand même sans referentiels plutôt que de planter."""
    arbres_dir = tmp_path / "arbres_actifs"
    arbres_dir.mkdir()
    (arbres_dir / "national.yaml").write_text(ARBRE_VALIDE_YAML, encoding="utf-8")

    def _raise():
        raise FileNotFoundError("referentiels.yaml absent")

    monkeypatch.setattr(validate_arbres_actifs, "load_referentiels", _raise)
    # Ne lève pas : l'arbre minimal n'a pas besoin de referentiel.
    call_command("validate_arbres_actifs", "--dir", str(tmp_path))


def test_arbres_valides_affiche_succes(tmp_path, capsys):
    arbres_dir = tmp_path / "arbres_actifs"
    arbres_dir.mkdir()
    (arbres_dir / "national.yaml").write_text(ARBRE_VALIDE_YAML, encoding="utf-8")
    call_command("validate_arbres_actifs", "--dir", str(tmp_path))
    out = capsys.readouterr().out
    assert "OK" in out
    assert "1 arbre(s) canonique(s) valide(s)" in out


@pytest.mark.parametrize(
    "filename,scope,region",
    [
        ("national.yaml", "national", ""),
        ("region_44.yaml", "region", "44"),
        ("zar_08.yaml", "zar", "08"),
    ],
)
def test_scope_from_filename_deduit_scope_et_region(filename, scope, region):
    assert validate_arbres_actifs.scope_from_filename(filename) == (scope, region)


def test_scope_from_filename_hors_convention_retourne_none():
    assert validate_arbres_actifs.scope_from_filename("n_importe_quoi.yaml") is None
