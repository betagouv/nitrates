"""QC redondantes (#620) : commande de normalisation, avertissements du
validateur, volet de reprise d'une question existante dans l'editeur."""

import copy
import json
from io import StringIO

import pytest
import yaml as pyyaml
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.urls import reverse
from django.utils import timezone

from envergo.nitrates.models import DecisionTree, DecisionTreeRevision
from envergo.nitrates.yaml_admin import editor
from envergo.nitrates.yaml_tree.qc_champs import iter_noeuds
from envergo.nitrates.yaml_tree.validator import avertissements_qc

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_nitrates")]

IAA = "Le fertilisant est-il issu de traitement de matières premières ?"
OUI_NON = [{"valeur": True, "libelle": "Oui"}, {"valeur": False, "libelle": "Non"}]


def qc(nid, champ, texte=IAA, branches=None):
    return {
        "type_noeud": "formulaire",
        "niveau": "complement",
        "id": nid,
        "champ": champ,
        "texte": texte,
        "branches": copy.deepcopy(
            branches
            if branches is not None
            else [
                {
                    "valeur": True,
                    "libelle": "Oui",
                    "regle": {"id": f"r_{nid}_oui", "type": "libre"},
                },
                {
                    "valeur": False,
                    "libelle": "Non",
                    "regle": {"id": f"r_{nid}_non", "type": "libre"},
                },
            ]
        ),
    }


def contenu(*noeuds):
    return {
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "culture",
                "id": "q_culture",
                "champ": "occupation_sol",
                "texte": "Culture ?",
                "branches": [
                    {"valeur": f"c{i}", "noeud": n} for i, n in enumerate(noeuds)
                ],
            }
        }
    }


@pytest.fixture(autouse=True)
def _purge():
    DecisionTree.objects.all().delete()


@pytest.fixture
def alice(db):
    return get_user_model().objects.create_user(
        email="alice@test.local", name="Alice", password="x", is_staff=True
    )


def actif(nom, data, scope="national", region_code="", weight=1):
    return DecisionTree.objects.create(
        name=nom,
        status=DecisionTree.STATUS_ACTIVE,
        scope=scope,
        region_code=region_code,
        weight=weight,
        contenu=data,
        contenu_yaml_brut=pyyaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        activated_at=timezone.now(),
    )


@pytest.fixture
def arbres():
    pan = actif(
        "PAN",
        contenu(
            qc("q_a", "fertilisant_iaa"),
            qc("q_b", "fertilisant_iaa"),
            qc("q_c", "icpe_ed"),
        ),
    )
    par = actif(
        "PAR GE",
        contenu(
            qc("q_d", "pas_un_digestats"),
            qc("q_e", "culture_irriguee", "Culture irriguée ?"),
        ),
        scope="region",
        region_code="44",
        weight=10,
    )
    return pan, par


def champs(tree):
    return sorted(
        {
            n["champ"]
            for n in iter_noeuds(tree.contenu)
            if n.get("niveau") == "complement"
        }
    )


# ─── Commande ───────────────────────────────────────────────────────────────


def test_dry_run_n_ecrit_rien(arbres):
    out = StringIO()
    call_command("normaliser_champs_qc", stdout=out)
    texte = out.getvalue()
    assert "fertilisant_iaa (champ retenu)" in texte
    assert "-> icpe_ed" in texte and "-> pas_un_digestats" in texte
    assert "DRY-RUN" in texte
    assert DecisionTree.objects.filter(status=DecisionTree.STATUS_DRAFT).count() == 0
    pan, _ = arbres
    pan.refresh_from_db()
    assert "icpe_ed" in champs(pan)


def test_apply_cree_des_brouillons_sans_toucher_aux_actifs(arbres, alice):
    pan, par = arbres
    call_command(
        "normaliser_champs_qc",
        "--apply",
        "--utilisateur",
        alice.email,
        stdout=StringIO(),
    )
    drafts = DecisionTree.objects.filter(status=DecisionTree.STATUS_DRAFT)
    assert {d.parent_id for d in drafts} == {pan.pk, par.pk}
    for d in drafts:
        assert d.created_by == alice
        assert "icpe_ed" not in champs(d) and "pas_un_digestats" not in champs(d)
        rev = DecisionTreeRevision.objects.get(tree=d)
        assert rev.action == DecisionTreeRevision.ACTION_RENAME
        assert "icpe_ed" in json.dumps(
            rev.previous_contenu
        ) or "pas_un_digestats" in json.dumps(rev.previous_contenu)
        # YAML brut coherent avec le contenu.
        assert pyyaml.safe_load(d.contenu_yaml_brut) == d.contenu
    pan.refresh_from_db()
    assert pan.status == DecisionTree.STATUS_ACTIVE and "icpe_ed" in champs(pan)


def test_activer_archive_les_anciens_actifs(arbres):
    call_command("normaliser_champs_qc", "--apply", "--activer", stdout=StringIO())
    actifs = DecisionTree.objects.filter(status=DecisionTree.STATUS_ACTIVE)
    assert actifs.count() == 2
    for t in actifs:
        assert set(champs(t)) <= {"fertilisant_iaa", "culture_irriguee"}
    assert DecisionTree.objects.filter(status=DecisionTree.STATUS_ARCHIVE).count() == 2


def test_groupe_restreint_l_application(arbres):
    actif(
        "ZAR",
        contenu(
            qc("q_f", "type_ii", "Fertirrigation ?"),
            qc("q_g", "fertirrigation", "Fertirrigation ?"),
            qc("q_h", "fertirrigation", "Fertirrigation ?"),
        ),
        scope="zar",
        region_code="44",
        weight=20,
    )
    call_command(
        "normaliser_champs_qc",
        "--apply",
        "--groupe",
        "fertirrigation",
        stdout=StringIO(),
    )
    drafts = list(DecisionTree.objects.filter(status=DecisionTree.STATUS_DRAFT))
    assert [d.name.split(" – ")[0] for d in drafts] == ["ZAR"]
    assert champs(drafts[0]) == ["fertirrigation"]


def test_activer_sans_apply_refuse(arbres):
    with pytest.raises(CommandError):
        call_command("normaliser_champs_qc", "--activer", stdout=StringIO())


def test_reference_non_reecrivable_annule_tout(arbres):
    pan, _ = arbres
    data = copy.deepcopy(pan.contenu)
    data["arbre"]["noeud"]["branches"].append(
        {
            "valeur": "c9",
            "noeud": {
                "type_noeud": "catalogue_parametre",
                "id": "n_param",
                "champ": "calc",
                "branches": [
                    {
                        "expression": "icpe_ed ==",
                        "regle": {"id": "r_param", "type": "libre"},
                    }
                ],
            },
        }
    )
    pan.contenu = data
    pan.save()
    with pytest.raises(CommandError):
        call_command("normaliser_champs_qc", "--apply", stdout=StringIO())
    assert DecisionTree.objects.filter(status=DecisionTree.STATUS_DRAFT).count() == 0


# ─── Validateur ─────────────────────────────────────────────────────────────


def test_avertissement_meme_question_deux_champs_dans_l_arbre():
    msgs = avertissements_qc(contenu(qc("q_a", "a"), qc("q_b", "b")))
    assert len(msgs) == 1 and msgs[0].startswith("[qc_redondante]")
    assert "a ('q_a')" in msgs[0] and "b ('q_b')" in msgs[0]


def test_avertissement_entre_arbres_et_valeurs_divergentes():
    plan_1 = [{"valeur": "icpe_a"}, {"valeur": "autre"}]
    plan_2 = [{"valeur": "icpe_a"}, {"valeur": "non_concerne"}]
    ici = contenu(qc("q_a", "icpe_ed"), qc("q_p", "plan_epandage", "Plan ?", plan_1))
    ailleurs = contenu(
        qc("q_b", "fertilisant_iaa"), qc("q_q", "plan_epandage", "Plan ?", plan_2)
    )
    msgs = avertissements_qc(ici, [("PAN", ailleurs)])
    assert any(
        "[qc_redondante]" in m and "fertilisant_iaa" in m and "« PAN »" in m
        for m in msgs
    )
    assert any(m.startswith("[qc_valeurs]") and "plan_epandage" in m for m in msgs)


def test_pas_d_avertissement_quand_tout_est_aligne():
    ici = contenu(qc("q_a", "fertilisant_iaa"))
    assert (
        avertissements_qc(ici, [("PAN", contenu(qc("q_b", "fertilisant_iaa")))]) == []
    )


def test_panneau_de_validation_affiche_les_avertissements(client, alice, arbres):
    pan, _ = arbres
    draft = DecisionTree.clone_to_draft(pan, user=alice)
    client.force_login(alice)
    resp = client.post(
        reverse("nitrates_admin_yaml_validate_tree", kwargs={"tree_pk": draft.pk})
    )
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "avertissement" in body and "qc_redondante" in body


# ─── Volet de reprise dans l'editeur ────────────────────────────────────────


@pytest.fixture
def draft(alice, arbres):
    pan, _ = arbres
    return DecisionTree.clone_to_draft(pan, user=alice)


def test_suggestions_proposent_les_questions_de_tous_les_arbres(client, alice, draft):
    client.force_login(alice)
    url = reverse("nitrates_admin_yaml_qc_suggestions", kwargs={"tree_pk": draft.pk})
    resp = client.get(url, {"c_texte": "issu de traitement de matières"})
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "fertilisant_iaa" in body and "pas_un_digestats" in body
    assert "Reprendre cette question" in body
    # Le brouillon remplace le PAN actif : ses questions ne comptent qu'une
    # fois (2 noeuds fertilisant_iaa, pas 4).
    assert "2 nœuds" in body and "4 nœuds" not in body


def test_suggestions_texte_identique_mis_en_avant(client, alice, draft):
    client.force_login(alice)
    url = reverse("nitrates_admin_yaml_qc_suggestions", kwargs={"tree_pk": draft.pk})
    body = client.get(url, {"texte": IAA}).content.decode()
    assert "Cette question existe déjà" in body and "Texte identique" in body


def test_suggestions_vides_sans_correspondance(client, alice, draft):
    client.force_login(alice)
    url = reverse("nitrates_admin_yaml_qc_suggestions", kwargs={"tree_pk": draft.pk})
    assert client.get(url, {"c_texte": "zzz qqq www"}).content == b""


def test_suggestions_reservees_au_staff(client, draft):
    url = reverse("nitrates_admin_yaml_qc_suggestions", kwargs={"tree_pk": draft.pk})
    assert client.get(url, {"c_texte": IAA}).status_code in (302, 403)


def test_ajout_avec_question_reprise_cree_les_reponses(client, alice, draft):
    client.force_login(alice)
    url = reverse("nitrates_admin_yaml_add_child", kwargs={"tree_pk": draft.pk})
    resp = client.post(
        url + "?path=q_culture",
        {
            "valeur": "c_nouvelle",
            "kind": "noeud_formulaire_complement",
            "c_texte": IAA,
            "c_champ": "fertilisant_iaa",
            "c_branches_existantes": json.dumps(OUI_NON),
        },
    )
    assert resp.status_code == 200
    draft.refresh_from_db()
    branche = next(
        b
        for b in draft.contenu["arbre"]["noeud"]["branches"]
        if b["valeur"] == "c_nouvelle"
    )
    assert branche["noeud"]["champ"] == "fertilisant_iaa"
    assert branche["noeud"]["branches"] == OUI_NON


def test_edition_avec_question_reprise_ajoute_les_reponses_manquantes(
    client, alice, draft
):
    data = copy.deepcopy(draft.contenu)
    data["arbre"]["noeud"]["branches"].append(
        {
            "valeur": "c_vide",
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "complement",
                "id": "q_vide",
                "champ": "nouveau",
                "texte": "Brouillon",
                "branches": [{"valeur": True, "libelle": "Oui, déjà là"}],
            },
        }
    )
    draft.contenu = data
    draft.save()
    client.force_login(alice)
    url = reverse("nitrates_admin_yaml_edit_node", kwargs={"tree_pk": draft.pk})
    resp = client.post(
        url + "?path=q_culture/q_vide",
        {
            "id": "q_vide",
            "niveau": "complement",
            "texte": IAA,
            "champ": "fertilisant_iaa",
            "aide": "",
            "branches_existantes": json.dumps(OUI_NON),
        },
    )
    assert resp.status_code == 200
    assert resp["HX-Retarget"] == "#node-q_cultureq_vide"
    draft.refresh_from_db()
    noeud = editor.get_node_at(draft.contenu, ("q_culture", "q_vide"))
    assert noeud["champ"] == "fertilisant_iaa"
    # La reponse existante est gardee telle quelle, la manquante est ajoutee.
    assert noeud["branches"] == [
        {"valeur": True, "libelle": "Oui, déjà là"},
        {"valeur": False, "libelle": "Non"},
    ]


def test_formulaires_branchent_le_volet(client, alice, draft):
    client.force_login(alice)
    url = reverse("nitrates_admin_yaml_add_child", kwargs={"tree_pk": draft.pk})
    body = client.get(
        url + "?path=q_culture&kind=noeud_formulaire_complement"
    ).content.decode()
    assert "data-qc-volet" in body and 'name="c_branches_existantes"' in body
    assert (
        reverse("nitrates_admin_yaml_qc_suggestions", kwargs={"tree_pk": draft.pk})
        in body
    )
    edit = reverse("nitrates_admin_yaml_edit_node", kwargs={"tree_pk": draft.pk})
    body = client.get(edit + "?path=q_culture/q_a").content.decode()
    assert "data-qc-volet" in body and 'name="branches_existantes"' in body
