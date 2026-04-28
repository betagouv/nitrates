"""Tests unitaires des modules yaml_admin/ (flatten + tags)."""

from envergo.nitrates.yaml_admin.flatten import iter_entries
from envergo.nitrates.yaml_admin.tags import (
    get_tags,
    has_a_completer,
    subtree_has_calculatrice,
)

SAMPLE = {
    "arbre": {
        "noeud": {
            "type_noeud": "catalogue",
            "id": "n_root",
            "champ": "z",
            "source": "sig",
            "branches": [
                {
                    "valeur": True,
                    "noeud": {
                        "type_noeud": "formulaire",
                        "niveau": "culture",
                        "id": "q_culture",
                        "champ": "c",
                        "branches": [
                            {
                                "valeur": "x",
                                "regle": {"id": "r_x", "type": "interdiction"},
                            },
                            {
                                "valeur": "y",
                                "regle": {
                                    "id": "r_y",
                                    "type": "calculatrice",
                                    "composant": "fenetre_epandage",
                                },
                            },
                            {"valeur": "z", "renvoi_vers": "r_x"},
                            {
                                "valeur": "todo",
                                "regle": {"id": "r_todo", "a_completer": True},
                            },
                        ],
                    },
                }
            ],
        }
    }
}


def test_iter_entries_visits_all_kinds():
    kinds = [e.kind for e in iter_entries(SAMPLE)]
    assert kinds.count("noeud") == 2  # racine + q_culture
    assert kinds.count("branche") == 5  # 1 (true) + 4 (x, y, z, todo)
    assert kinds.count("regle") == 3
    assert kinds.count("renvoi_vers") == 1


def test_iter_entries_paths_unique():
    paths = [e.path for e in iter_entries(SAMPLE)]
    assert len(paths) == len(set(paths)), "chaque entree doit avoir un path unique"


def test_iter_entries_depth_increases():
    depths = [e.depth for e in iter_entries(SAMPLE)]
    assert depths[0] == 0
    assert max(depths) >= 3  # racine -> branche -> noeud -> branche -> regle


def test_iter_entries_handles_empty_tree():
    assert list(iter_entries({})) == []
    assert list(iter_entries({"arbre": {}})) == []


def test_get_tags_catalogue():
    tags = get_tags("noeud", {"type_noeud": "catalogue", "source": "sig"})
    labels = [t.label for t in tags]
    assert "catalogue" in labels
    assert "sig" in labels


def test_get_tags_formulaire_niveau():
    tags = get_tags("noeud", {"type_noeud": "formulaire", "niveau": "type_fertilisant"})
    assert any(t.css == "tag-form-fertilisant" for t in tags)


def test_get_tags_regle_types():
    for rtype, css in [
        ("interdiction", "tag-regle-interdiction"),
        ("autorisation_sous_condition", "tag-regle-autorisation"),
        ("plafonnement", "tag-regle-plafonnement"),
        ("libre", "tag-regle-libre"),
        ("non_applicable", "tag-regle-non-applicable"),
        ("calculatrice", "tag-regle-calculatrice"),
    ]:
        tags = get_tags("regle", {"type": rtype})
        assert any(t.css == css for t in tags), f"{rtype} sans tag attendu"


def test_get_tags_a_completer_added():
    tags = get_tags("regle", {"type": "interdiction", "a_completer": True})
    assert any(t.css == "tag-a-completer" for t in tags)


def test_has_a_completer_finds_deep():
    assert has_a_completer(SAMPLE["arbre"]["noeud"]) is True


def test_has_a_completer_negative():
    sub = {
        "branches": [
            {"valeur": "ok", "regle": {"id": "r_ok", "type": "libre"}},
        ]
    }
    assert has_a_completer(sub) is False


def test_subtree_has_calculatrice_finds():
    assert subtree_has_calculatrice(SAMPLE["arbre"]["noeud"]) is True


def test_subtree_has_calculatrice_negative():
    sub = {
        "branches": [
            {"valeur": "ok", "regle": {"id": "r_ok", "type": "interdiction"}},
        ]
    }
    assert subtree_has_calculatrice(sub) is False
