"""Bug : les liens de navigation de l'editeur (filtres, vues, reset fold)
faisaient sortir silencieusement du mode edition. La cause : `mode=edition`
n'etait pas reinjecte dans les querystrings generes par `_querystring_base`
ni dans les liens directs filtres/vues du template `tree.html`.

Symptome user-facing decrit dans l'issue #80 :
> "Refermer tout" sauvegarde l'arbre et sort de l'edition.

Le "refermer tout" correspond a `↺ Reinitialiser le pli` (efface
expand/expand_deep), qui passait par `reset_link querystring_base`. Comme
mode=edition n'etait pas dans le base, le clic ramenait l'utilisateur en
mode lecture. Le brouillon restait sauvegarde (auto-save par modif) d'ou
le ressenti "save + sortie".
"""

import textwrap

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from envergo.nitrates.models import DecisionTree

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_nitrates")]


@pytest.fixture(autouse=True)
def _purge():
    DecisionTree.objects.all().delete()


@pytest.fixture
def staff_user(db):
    User = get_user_model()
    return User.objects.create_user(
        email="staff@test.local", name="Staff", password="x", is_staff=True
    )


@pytest.fixture
def draft_tree(make_active_tree):
    yaml_text = textwrap.dedent(
        """\
        metadata:
          version: "0.0.1-test"
        arbre:
          noeud:
            type_noeud: "catalogue"
            id: "n_root"
            champ: "en_zv"
            source: "sig"
            branches:
              - valeur: true
                noeud:
                  type_noeud: "formulaire"
                  niveau: "culture"
                  id: "q_culture"
                  texte: "Quelle culture ?"
                  champ: "occupation_sol"
                  branches:
                    - valeur: "colza"
                      regle:
                        id: "r_colza"
                        type: "interdiction"
        """
    )
    active = make_active_tree(yaml_text)
    draft = DecisionTree.objects.create(
        name=active.name,
        status=DecisionTree.STATUS_DRAFT,
        contenu=active.contenu,
        contenu_yaml_brut=active.contenu_yaml_brut,
        parent=active,
    )
    return draft


def _edit_url(tree):
    return reverse("nitrates_admin_yaml_tree") + f"?tree_id={tree.pk}&mode=edition"


def test_filtre_links_preserve_mode_edition(client, staff_user, draft_tree):
    """Les liens "Filtres" (Tout / interdiction / autorisation / ...) en haut
    de page doivent inclure `mode=edition` quand on est en edition."""
    client.force_login(staff_user)
    resp = client.get(_edit_url(draft_tree))
    assert resp.status_code == 200
    body = resp.content.decode()
    # Le lien "Tout" (sans filtre, juste tree_id + mode) doit etre present.
    assert (
        f'href="?tree_id={draft_tree.pk}&mode=edition"' in body
    ), "lien Tout doit conserver mode=edition"
    # Le bloc nav__quick doit contenir mode=edition dans chaque lien (>= 2).
    nav_start = body.find('class="yaml-admin__quick"')
    nav_end = body.find("</nav>", nav_start)
    nav_html = body[nav_start:nav_end]
    assert nav_html.count("mode=edition") >= 2, (
        f"tous les liens filtre doivent inclure mode=edition, "
        f"trouve {nav_html.count('mode=edition')}"
    )


def test_vue_links_preserve_mode_edition(client, staff_user, draft_tree):
    """Les liens "Vue" (Arbre / Arbre + YAML / YAML brut) doivent inclure
    `mode=edition`."""
    client.force_login(staff_user)
    body = client.get(_edit_url(draft_tree)).content.decode()
    # Bloc vues :
    vues_start = body.find('class="yaml-admin__vues"')
    vues_end = body.find("</div>", vues_start)
    vues_html = body[vues_start:vues_end]
    # 3 liens (Arbre, Arbre+YAML, YAML brut) doivent tous avoir mode=edition.
    assert (
        vues_html.count("mode=edition") == 3
    ), f"3 liens de vue, chacun avec mode=edition, trouve {vues_html.count('mode=edition')}"


def test_reset_fold_link_preserves_mode_edition(client, staff_user, draft_tree):
    """Le lien `↺ Reinitialiser le pli` (bug "Refermer tout" originel) doit
    rester en mode edition."""
    client.force_login(staff_user)
    # On force un expand pour faire apparaitre le bouton reset.
    url = _edit_url(draft_tree) + "&expand=n_root"
    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    # Le bouton Reinitialiser le pli existe :
    assert (
        "Réinitialiser le pli" in body
    ), "bouton reset doit apparaitre quand expand est present"
    # Et le lien associe doit contenir mode=edition.
    # On extrait le href du bouton :
    btn_start = body.find("Réinitialiser le pli")
    # Cherche le href le plus proche au-dessus
    href_idx = body.rfind('href="', 0, btn_start)
    href_end = body.find('"', href_idx + 6)
    href = body[href_idx + 6 : href_end]  # noqa: E203
    assert (
        "mode=edition" in href
    ), f"reset link doit contenir mode=edition, href = {href}"


def test_lecture_mode_does_not_inject_mode_edition(client, staff_user, draft_tree):
    """Securite inverse : en mode lecture, on n'injecte PAS mode=edition
    dans les liens (ca serait une redirection involontaire vers l'edition)."""
    client.force_login(staff_user)
    body = client.get(
        reverse("nitrates_admin_yaml_tree") + f"?tree_id={draft_tree.pk}"
    ).content.decode()
    # Les liens vue/filtre ne doivent PAS contenir mode=edition.
    vues_start = body.find('class="yaml-admin__vues"')
    vues_end = body.find("</div>", vues_start)
    assert "mode=edition" not in body[vues_start:vues_end]
