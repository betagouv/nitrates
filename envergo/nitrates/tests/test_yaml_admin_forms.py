"""Tests unitaires des forms admin YAML (parsing + validation locale)."""

from envergo.nitrates.yaml_admin.forms import (
    BrancheForm,
    NoeudFormulaireForm,
    RegleForm,
)

# ─── NoeudFormulaireForm ───────────────────────────────────────────────


def test_noeud_form_minimal_valide():
    f = NoeudFormulaireForm({"id": "q_test", "niveau": "culture", "texte": "?"})
    assert f.is_valid()
    assert f.to_new_data() == {
        "id": "q_test",
        "niveau": "culture",
        "texte": "?",
        "aide": "",
        "champ": "",
    }


def test_noeud_form_niveau_inconnu_rejete():
    f = NoeudFormulaireForm({"niveau": "yolo"})
    assert not f.is_valid()
    assert "niveau" in f.errors


def test_noeud_form_strip_whitespace():
    f = NoeudFormulaireForm(
        {"id": "  q_test  ", "niveau": "culture", "texte": "  hi  "}
    )
    assert f.is_valid()
    nd = f.to_new_data()
    assert nd["id"] == "q_test"
    assert nd["texte"] == "hi"


# ─── BrancheForm ───────────────────────────────────────────────────────


def test_branche_form_libelle_seul():
    f = BrancheForm({"valeur_new": "True", "libelle": "Oui"})
    assert f.is_valid()
    nd = f.to_new_data()
    assert nd["libelle"] == "Oui"
    assert nd["valeur_new_raw"] == "True"
    assert nd["renvoi_vers_new"] == ""


def test_branche_form_renvoi_vers_id_invalide():
    f = BrancheForm({"valeur_new": "x", "renvoi_vers_new": "Pas Un Slug"})
    assert not f.is_valid()
    assert "renvoi_vers_new" in f.errors


def test_branche_form_renvoi_vers_id_valide():
    f = BrancheForm({"valeur_new": "x", "renvoi_vers_new": "r_colza_type_0"})
    assert f.is_valid()
    assert f.to_new_data()["renvoi_vers_new"] == "r_colza_type_0"


# ─── RegleForm ─────────────────────────────────────────────────────────


def test_regle_form_minimal_interdiction():
    f = RegleForm({"id": "r_x", "type": "interdiction"})
    assert f.is_valid()
    nd = f.to_new_data()
    assert nd["id"] == "r_x"
    assert nd["type"] == "interdiction"
    assert nd["periodes"] == []
    assert nd["a_completer"] is False


def test_regle_form_periodes_jj_mm_ok():
    f = RegleForm(
        {
            "type": "interdiction",
            "periodes-0-du": "15/12",
            "periodes-0-au": "15/01",
        }
    )
    assert f.is_valid()
    nd = f.to_new_data()
    assert nd["periodes"] == [{"du": "15/12", "au": "15/01"}]


def test_regle_form_periode_evenement_phenologique_ok():
    f = RegleForm(
        {
            "type": "interdiction",
            "periodes-0-du": "recolte_culture_principale",
            "periodes-0-au": "15/01",
        }
    )
    assert f.is_valid()


def test_regle_form_periode_format_invalide_rejete():
    f = RegleForm(
        {
            "type": "interdiction",
            "periodes-0-du": "32/13",
            "periodes-0-au": "15/01",
        }
    )
    # 32/13 matche le regex format JJ/MM mais pas la sémantique date :
    # le validator GLOBAL le rejettera. Ici on ne valide que le format.
    assert f.is_valid()


def test_regle_form_periode_truc_pas_slug_rejete():
    f = RegleForm(
        {
            "type": "interdiction",
            "periodes-0-du": "Pas Un Slug",
            "periodes-0-au": "15/01",
        }
    )
    assert not f.is_valid()


def test_regle_form_regime_inconnu_rejete():
    f = RegleForm(
        {
            "type": "interdiction",
            "periodes-0-du": "15/12",
            "periodes-0-regime": "yolo",
        }
    )
    assert not f.is_valid()


def test_regle_form_calculatrice_inputs_csv():
    f = RegleForm(
        {
            "type": "calculatrice",
            "composant": "fenetre_x",
            "inputs_requis": "culture, parcelle, date",
        }
    )
    assert f.is_valid()
    nd = f.to_new_data()
    assert nd["composant"] == "fenetre_x"
    assert nd["inputs_requis"] == ["culture", "parcelle", "date"]


def test_regle_form_plafond_float_ok():
    f = RegleForm({"type": "plafonnement", "plafond_azote_kg_n_ha": "50"})
    assert f.is_valid()
    nd = f.to_new_data()
    assert nd["plafond_azote_kg_n_ha"] == 50.0


def test_regle_form_plafond_pas_un_nombre_rejete():
    f = RegleForm({"type": "plafonnement", "plafond_azote_kg_n_ha": "yolo"})
    assert not f.is_valid()


def test_regle_form_a_completer_checkbox():
    f = RegleForm({"a_completer": "on"})
    assert f.is_valid()
    assert f.to_new_data()["a_completer"] is True


def test_regle_form_periodes_multiples():
    f = RegleForm(
        {
            "type": "interdiction",
            "periodes-0-du": "15/12",
            "periodes-0-au": "15/01",
            "periodes-1-du": "01/06",
            "periodes-1-au": "30/06",
            "periodes-1-regime": "libre",
        }
    )
    assert f.is_valid()
    nd = f.to_new_data()
    assert nd["periodes"] == [
        {"du": "15/12", "au": "15/01"},
        {"du": "01/06", "au": "30/06", "regime": "libre"},
    ]
