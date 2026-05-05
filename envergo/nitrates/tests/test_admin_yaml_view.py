"""Tests du viewer admin YAML (phase 2bis, read-only).

Couvre :
  - acces protege par staff_member_required
  - rendu des primitives (formulaire / catalogue / regle / renvoi_vers)
  - filtres ?filtre=a_completer / calculatrices
  - toggle ?vue=arbre / split / brut
  - le YAML brut est colore par Pygments
"""

import textwrap

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_nitrates")]


@pytest.fixture
def specs_dir(tmp_path, settings, make_active_tree):
    """Cree un DecisionTree actif minimal qui couvre toutes les primitives :
    catalogue racine, formulaire (4 niveaux ordonnes), regles
    (interdiction, autorisation, plafonnement, libre, non_applicable,
    calculatrice), renvoi_vers, a_completer.

    Garde son ancien nom (`specs_dir`) pour minimiser le diff sur les tests
    qui l'utilisent. Garde aussi l'ecriture sur disque + NITRATES_SPECS_DIR
    pour que le test `test_loader_roundtrip_preserves_content` qui appelle
    le loader fichier (ruamel) continue de marcher.
    """
    yaml_text = textwrap.dedent(
        """\
        metadata:
          version: "0.0.1-test"
          source: "fixture"
          statut: "test"
          derniere_maj: "2026-04-28"
        arbre:
          noeud:
            type_noeud: "catalogue"
            id: "n_zvn"
            champ: "en_zone_vulnerable"
            source: "sig"
            reference: "zone_vulnerable_nitrates"
            branches:
              - valeur: false
                libelle: "Non"
                regle:
                  id: "r_hors_zvn"
                  type: "non_applicable"
                  message: "ZV non concernee."
              - valeur: true
                libelle: "Oui"
                noeud:
                  type_noeud: "formulaire"
                  niveau: "culture"
                  id: "q_occupation"
                  texte: "Occupation ?"
                  champ: "occupation"
                  branches:
                    - valeur: "sol_non_cultive"
                      regle:
                        id: "r_sol_non_cultive"
                        type: "interdiction"
                        periodes:
                          - du: "01/01"
                            au: "31/12"
                    - valeur: "culture_principale"
                      noeud:
                        type_noeud: "formulaire"
                        niveau: "sous_culture"
                        id: "q_sous"
                        texte: "Quelle culture ?"
                        champ: "sous_culture"
                        branches:
                          - valeur: "colza"
                            noeud:
                              type_noeud: "formulaire"
                              niveau: "type_fertilisant"
                              id: "q_fert"
                              texte: "Type ?"
                              champ: "type_fertilisant"
                              branches:
                                - valeur: "type_0"
                                  regle:
                                    id: "r_colza_t0"
                                    type: "interdiction"
                                    periodes:
                                      - du: "15/12"
                                        au: "15/01"
                                    code_prescription: "pc4"
                                - valeur: "type_II"
                                  regle:
                                    id: "r_colza_t2"
                                    type: "autorisation_sous_condition"
                                    texte_condition: "ICPE"
                                - valeur: "type_III"
                                  renvoi_vers: "r_colza_t0"
                          - valeur: "luzerne"
                            regle:
                              id: "r_luzerne_libre"
                              type: "libre"
                              plafonnement_associe: "r_plafond_luzerne"
                          - valeur: "cipan"
                            regle:
                              id: "r_cipan_calc"
                              type: "calculatrice"
                              composant: "fenetre_epandage"
                              inputs_requis:
                                - "date_semis"
                              parametres:
                                periode:
                                  du: "15/11"
                                  au: "15/01"
                          - valeur: "a_finir"
                            regle:
                              id: "r_todo"
                              a_completer: true
        plafonnements:
          - regle:
              id: "r_plafond_luzerne"
              type: "plafonnement"
              plafond_azote_kg_n_ha: 70
        """
    )
    (tmp_path / "arbre_decision_national.yaml").write_text(yaml_text, encoding="utf-8")
    settings.NITRATES_SPECS_DIR = str(tmp_path)
    make_active_tree(yaml_text)
    return tmp_path


@pytest.fixture
def staff_user(db):
    User = get_user_model()
    return User.objects.create_user(
        email="staff@test.local", name="Staff", password="x", is_staff=True
    )


@pytest.fixture
def regular_user(db):
    User = get_user_model()
    return User.objects.create_user(email="user@test.local", name="User", password="x")


@pytest.fixture
def url():
    return reverse("nitrates_admin_yaml_tree")


# ─── Acces ─────────────────────────────────────────────────────────────────


def test_anonymous_redirected_to_login(client, url, specs_dir):
    resp = client.get(url)
    assert resp.status_code in (302, 301)
    assert "/admin/login" in resp["Location"] or "/login" in resp["Location"]


def test_non_staff_redirected(client, url, specs_dir, regular_user):
    client.force_login(regular_user)
    resp = client.get(url)
    assert resp.status_code in (302, 301)


def test_staff_can_access(client, url, specs_dir, staff_user):
    client.force_login(staff_user)
    resp = client.get(url)
    assert resp.status_code == 200


# ─── Rendu des primitives ──────────────────────────────────────────────────


def test_renders_catalogue_root(client, url, specs_dir, staff_user):
    client.force_login(staff_user)
    resp = client.get(url)
    body = resp.content.decode()
    assert "n_zvn" in body
    assert "catalogue" in body.lower()


def test_renders_formulaire_levels(client, url, specs_dir, staff_user):
    client.force_login(staff_user)
    body = client.get(url).content.decode()
    for nid in ("q_occupation", "q_sous", "q_fert"):
        assert nid in body, f"noeud {nid} absent du rendu"
    # tags des niveaux
    assert "culture" in body.lower()
    assert "sous-culture" in body.lower() or "sous_culture" in body
    assert "fertilisant" in body.lower()


def test_renders_all_regle_types(client, url, specs_dir, staff_user):
    client.force_login(staff_user)
    body = client.get(url).content.decode()
    # Au moins 1 regle de chaque type rendue
    for rid in (
        "r_hors_zvn",
        "r_sol_non_cultive",
        "r_colza_t0",
        "r_colza_t2",
        "r_luzerne_libre",
        "r_cipan_calc",
        "r_todo",
    ):
        assert rid in body, f"regle {rid} absente du rendu"


def test_renders_renvoi_vers(client, url, specs_dir, staff_user):
    client.force_login(staff_user)
    body = client.get(url).content.decode()
    assert "renvoi" in body.lower()
    assert "r_colza_t0" in body  # cible du renvoi_vers


def test_renders_a_completer_marker(client, url, specs_dir, staff_user):
    client.force_login(staff_user)
    body = client.get(url).content.decode()
    assert "r_todo" in body
    assert "a-completer" in body.lower() or "à compléter" in body.lower()


# ─── Filtres ───────────────────────────────────────────────────────────────


def test_filter_a_completer_keeps_path(client, url, specs_dir, staff_user):
    client.force_login(staff_user)
    body = client.get(url + "?filtre=a_completer").content.decode()
    # le chemin q_occupation -> q_sous -> r_todo doit rester visible
    assert "q_occupation" in body
    assert "r_todo" in body


def test_filter_calculatrices_keeps_path(client, url, specs_dir, staff_user):
    client.force_login(staff_user)
    body = client.get(url + "?filtre=calculatrices").content.decode()
    assert "r_cipan_calc" in body


def test_invalid_filter_silently_ignored(client, url, specs_dir, staff_user):
    client.force_login(staff_user)
    resp = client.get(url + "?filtre=injection<script>")
    assert resp.status_code == 200


# ─── Toggle vue ────────────────────────────────────────────────────────────


def test_view_arbre_default(client, url, specs_dir, staff_user):
    client.force_login(staff_user)
    body = client.get(url).content.decode()
    assert "yaml-tree" in body
    # pas de bloc raw par defaut
    assert "yaml-admin__raw" not in body


def test_view_brut_includes_pygments(client, url, specs_dir, staff_user):
    client.force_login(staff_user)
    body = client.get(url + "?vue=brut").content.decode()
    assert "yaml-admin__raw" in body
    # markup Pygments : presence d'au moins une classe Pygments
    assert 'class="' in body
    # Le contenu YAML brut doit etre present (apres echappement HTML)
    assert "n_zvn" in body


def test_view_split_includes_both(client, url, specs_dir, staff_user):
    client.force_login(staff_user)
    body = client.get(url + "?vue=split").content.decode()
    assert "yaml-tree" in body
    assert "yaml-admin__raw" in body


def test_invalid_view_falls_back_to_arbre(client, url, specs_dir, staff_user):
    client.force_login(staff_user)
    body = client.get(url + "?vue=lol").content.decode()
    assert "yaml-tree" in body
    assert "yaml-admin__raw" not in body


# ─── Round-trip ruamel ─────────────────────────────────────────────────────


# ─── Barre de filtres rapides ──────────────────────────────────────────────


def test_quick_filter_buttons_rendered(client, url, specs_dir, staff_user):
    client.force_login(staff_user)
    body = client.get(url).content.decode()
    # Au moins quelques boutons attendus en barre rapide
    assert "yaml-admin__quick" in body
    for label in (
        "interdiction",
        "calculatrice",
        "fertilisant",
        "catalogue",
        "renvoi",
    ):
        assert label.lower() in body.lower(), f"label {label} absent du toolbar"


def test_quick_filter_active_marked(client, url, specs_dir, staff_user):
    client.force_login(staff_user)
    body = client.get(url + "?filtre=calculatrice").content.decode()
    assert "is-active" in body


def test_quick_filter_invalid_falls_back_to_none(client, url, specs_dir, staff_user):
    client.force_login(staff_user)
    resp = client.get(url + "?filtre=injection")
    assert resp.status_code == 200
    # filtre invalide → bouton "Tout" actif, aucun autre is-active
    body = resp.content.decode()
    assert "is-active" in body  # le bouton "Tout"


# ─── Expand dans l'URL ─────────────────────────────────────────────────────


def test_expand_param_persists_in_links(client, url, specs_dir, staff_user):
    client.force_login(staff_user)
    body = client.get(url + "?expand=n_zvn/q_occupation").content.decode()
    # Le lien deep d'un noeud doit refleter l'expand existant pour ne pas le perdre
    # On verifie au minimum que la page se charge et contient un lien expand_deep
    assert "expand_deep=" in body


def test_expand_deep_param_keeps_subtree_open(client, url, specs_dir, staff_user):
    client.force_login(staff_user)
    # Sans expand_deep, q_fert (depth 3) devrait etre dans un details ferme
    body_no_expand = client.get(url).content.decode()
    # Avec expand_deep racine, tout est ouvert
    body_deep = client.get(url + "?expand_deep=n_zvn").content.decode()
    # Heuristique : plus de balises <details open> dans le mode deep
    assert body_deep.count("open>") > body_no_expand.count("open>")


def test_reset_link_appears_only_when_expanded(client, url, specs_dir, staff_user):
    client.force_login(staff_user)
    plain = client.get(url).content.decode()
    expanded = client.get(url + "?expand_deep=n_zvn").content.decode()
    assert "Réinitialiser" not in plain
    assert "Réinitialiser" in expanded


def test_loader_roundtrip_preserves_content(specs_dir):
    """Verification de base : ruamel charge + redump conserve les ids et
    valeurs. (On ne verifie pas la byte-equality : c'est l'objet de la
    phase 3bis.1)."""
    from envergo.nitrates.yaml_admin.loader import dump_to_string, load_arbre_admin

    arbre = load_arbre_admin()
    redumped = dump_to_string(arbre)
    # Tous les ids critiques sont bien re-serialises
    for nid in (
        "n_zvn",
        "q_occupation",
        "r_colza_t0",
        "r_cipan_calc",
        "r_plafond_luzerne",
    ):
        assert nid in redumped
