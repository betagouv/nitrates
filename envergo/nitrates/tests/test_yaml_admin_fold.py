"""Tests de la logique de fold (compute_open_paths) et des nouveaux
filtres rapides par tag."""

from envergo.nitrates.yaml_admin.fold import compute_open_paths, node_path
from envergo.nitrates.yaml_admin.tags import (
    QUICK_FILTER_KEYS,
    matches_filter,
    subtree_matches,
)

TREE = {
    "type_noeud": "catalogue",
    "id": "n_root",
    "branches": [
        {
            "valeur": True,
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "culture",
                "id": "q_culture",
                "branches": [
                    {
                        "valeur": "colza",
                        "noeud": {
                            "type_noeud": "formulaire",
                            "niveau": "type_fertilisant",
                            "id": "q_fert",
                            "branches": [
                                {
                                    "valeur": "t0",
                                    "regle": {
                                        "id": "r_t0",
                                        "type": "interdiction",
                                    },
                                },
                                {
                                    "valeur": "calc",
                                    "regle": {
                                        "id": "r_calc",
                                        "type": "calculatrice",
                                    },
                                },
                            ],
                        },
                    },
                    {
                        "valeur": "luzerne",
                        "regle": {"id": "r_l", "type": "libre"},
                    },
                ],
            },
        }
    ],
}


# ─── Defaut : depth 0-1 ouvert ──────────────────────────────────────────────


def test_default_opens_only_root_and_depth_one():
    opened = compute_open_paths(TREE)
    assert "n_root" in opened
    assert "n_root/q_culture" in opened
    # q_fert est a depth 2 → ferme
    assert "n_root/q_culture/q_fert" not in opened


def test_default_with_empty_tree_returns_empty():
    assert compute_open_paths({}) == set()
    assert compute_open_paths(None) == set()


# ─── expand exact ───────────────────────────────────────────────────────────


def test_expand_opens_specific_path():
    opened = compute_open_paths(TREE, expand={"n_root/q_culture/q_fert"})
    assert "n_root/q_culture/q_fert" in opened


def test_expand_does_not_open_descendants():
    """Un expand=n_root n'ouvre que n_root, pas q_culture (qui de toute
    facon est ouvert par defaut). On verifie q_fert ferme."""
    opened = compute_open_paths(TREE, expand={"n_root"})
    assert "n_root/q_culture/q_fert" not in opened


# ─── expand_deep recursif ───────────────────────────────────────────────────


def test_expand_deep_opens_subtree():
    opened = compute_open_paths(TREE, expand_deep={"n_root/q_culture"})
    assert "n_root/q_culture/q_fert" in opened


def test_expand_deep_root_opens_everything():
    opened = compute_open_paths(TREE, expand_deep={"n_root"})
    assert "n_root" in opened
    assert "n_root/q_culture" in opened
    assert "n_root/q_culture/q_fert" in opened


# ─── Filtre actif ───────────────────────────────────────────────────────────


def test_filter_calculatrice_opens_ancestors_only():
    """Sous filtre `calculatrice`, on ouvre les ancetres jusqu'au parent
    direct du nœud qui contient la regle calculatrice. q_fert (parent
    direct de r_calc) est ouvert pour montrer la regle. Mais un nœud
    qui matche lui-meme un autre filtre (ex: 'type_fertilisant') ne
    doit PAS s'ouvrir sur lui-meme — on veut voir son titre."""
    opened = compute_open_paths(TREE, filtre="calculatrice")
    assert "n_root" in opened
    assert "n_root/q_culture" in opened
    # q_fert contient une regle calculatrice en descendant direct → ouvert
    assert "n_root/q_culture/q_fert" in opened


def test_filter_on_node_type_does_not_open_matching_node():
    """Cas typique : filtre 'type_fertilisant' ouvre les ancetres de
    chaque q_fert (n_root, q_culture), mais q_fert lui-meme reste
    ferme (on voit son titre dans la liste, pas ses regles dessous)."""
    opened = compute_open_paths(TREE, filtre="type_fertilisant")
    assert "n_root" in opened
    assert "n_root/q_culture" in opened
    # q_fert est le noeud qui matche → reste ferme
    assert "n_root/q_culture/q_fert" not in opened


def test_filter_keeps_only_matching_branches():
    """Sous filtre, q_fert ouvert (contient calculatrice en descendant
    strict). Si on n'avait pas de calculatrice sous q_fert, q_fert serait
    ferme."""
    tree_sans_calc = {
        "type_noeud": "catalogue",
        "id": "n_root",
        "branches": [
            {
                "valeur": True,
                "noeud": {
                    "type_noeud": "formulaire",
                    "niveau": "culture",
                    "id": "q_a",
                    "branches": [
                        {
                            "valeur": "x",
                            "regle": {"id": "r_x", "type": "interdiction"},
                        }
                    ],
                },
            }
        ],
    }
    opened = compute_open_paths(tree_sans_calc, filtre="calculatrice")
    assert opened == set()


def test_filter_overrides_expand():
    """Quand un filtre est actif, expand n'a pas d'effet supplementaire :
    seuls les chemins qui matchent restent ouverts."""
    opened = compute_open_paths(
        TREE, filtre="libre", expand={"n_root/q_culture/q_fert"}
    )
    # q_fert ne contient pas de libre → ferme malgre expand
    assert "n_root/q_culture/q_fert" not in opened


# ─── matches_filter ─────────────────────────────────────────────────────────


def test_matches_filter_culture():
    assert matches_filter(
        "culture", "noeud", {"type_noeud": "formulaire", "niveau": "culture"}
    )
    assert not matches_filter(
        "culture", "noeud", {"type_noeud": "formulaire", "niveau": "sous_culture"}
    )


def test_matches_filter_renvoi():
    assert matches_filter("renvoi", "renvoi_vers", {"valeur": "x"})
    assert not matches_filter("renvoi", "noeud", {"id": "x"})


def test_matches_filter_a_completer():
    assert matches_filter("a_completer", "regle", {"a_completer": True})
    assert not matches_filter("a_completer", "regle", {"a_completer": False})
    assert not matches_filter("a_completer", "regle", {"id": "x"})


def test_matches_filter_each_regle_type():
    for f, rtype in [
        ("interdiction", "interdiction"),
        ("autorisation", "autorisation_sous_condition"),
        ("plafonnement", "plafonnement"),
        ("libre", "libre"),
        ("non_applicable", "non_applicable"),
        ("calculatrice", "calculatrice"),
    ]:
        assert matches_filter(f, "regle", {"type": rtype})


def test_subtree_matches_finds_deep():
    assert subtree_matches("calculatrice", TREE)
    assert subtree_matches("libre", TREE)
    assert not subtree_matches("plafonnement", TREE)


def test_quick_filter_keys_complete():
    """Toutes les cles de filtre rapide sont bien declarees."""
    expected = {
        "culture",
        "sous_culture",
        "type_fertilisant",
        "complement",
        "catalogue",
        "interdiction",
        "autorisation",
        "plafonnement",
        "libre",
        "non_applicable",
        "calculatrice",
        "renvoi",
        "a_completer",
    }
    assert QUICK_FILTER_KEYS == expected


# ─── node_path helper ───────────────────────────────────────────────────────


def test_node_path_root():
    assert node_path([], "n_root") == "n_root"


def test_node_path_nested():
    assert node_path(["a", "b"], "c") == "a/b/c"
