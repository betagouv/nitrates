"""Historique des PC et contenus riches (RevisionContenu)."""

import json

import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from envergo.nitrates import historique
from envergo.nitrates.admin_historique import textes_rendus
from envergo.nitrates.models import CodePrescription, ContenuRichDSFR, RevisionContenu
from envergo.users.models import User

pytestmark = pytest.mark.django_db

BLOCS = {
    "schema": 1,
    "blocs": [
        {"type": "titre_principal", "data": {"texte": "Conditions"}},
        {
            "type": "liste",
            "data": {
                "items": [
                    {
                        "texte": "les conditions du PAR, notamment sur :",
                        "enfants": [{"texte": "la durée du couvert"}],
                    }
                ]
            },
        },
    ],
}


def _revisions(identifiant, type_objet=RevisionContenu.TYPE_PC):
    return list(
        RevisionContenu.objects.filter(
            type_objet=type_objet, identifiant=identifiant
        ).order_by("created_at", "pk")
    )


@pytest.fixture
def admin_client(db):
    user = User.objects.create(
        email="juriste@test.local", is_staff=True, is_superuser=True, is_active=True
    )
    client = Client()
    client.force_login(user)
    return client, user


def _post_pc(client, pc, **changes):
    data = {
        "identifiant": pc.identifiant,
        "mots_cles": pc.mots_cles,
        "texte_court": pc.texte_court,
        "texte_redaction_initiale": pc.texte_redaction_initiale,
        "blocs": json.dumps(pc.blocs),
        "scope": pc.scope,
        "region_code": pc.region_code,
        "ordre_affichage": pc.ordre_affichage,
    }
    data.update(changes)
    url = reverse("admin:nitrates_codeprescription_change", args=[pc.pk])
    return client.post(url, data)


def test_creation_puis_modification_orm():
    pc = CodePrescription.objects.create(identifiant="pc_h1", texte_court="t")
    pc.blocs = BLOCS
    pc.save()

    revs = _revisions("pc_h1")
    assert [r.action for r in revs] == ["creation", "modification"]
    assert revs[1].champs_modifies == ["blocs"]
    assert revs[1].instantane["blocs"] == BLOCS
    assert revs[1].environnement == "test"


def test_texte_court_non_suivi_et_sauvegarde_identique_sans_revision():
    pc = CodePrescription.objects.create(identifiant="pc_h2", texte_court="t")
    pc.texte_court = "autre"
    pc.texte_redaction_initiale = "autre"
    pc.save()
    pc.save()
    assert len(_revisions("pc_h2")) == 1


def test_admin_trace_auteur_motif_et_origine(admin_client):
    client, user = admin_client
    pc = CodePrescription.objects.create(identifiant="pc_h3", texte_court="t")

    resp = _post_pc(
        client,
        pc,
        blocs=json.dumps(BLOCS),
        plafond="on",
        motif_modification="copié depuis staging le 14/10",
    )

    assert resp.status_code == 302
    rev = _revisions("pc_h3")[-1]
    assert rev.origine == RevisionContenu.ORIGINE_ADMIN
    assert rev.auteur == user
    assert rev.motif == "copié depuis staging le 14/10"
    assert rev.champs_modifies == ["blocs", "plafond"]


def test_admin_motif_obligatoire(admin_client):
    client, _ = admin_client
    pc = CodePrescription.objects.create(identifiant="pc_h4", texte_court="t")

    resp = _post_pc(client, pc, blocs=json.dumps(BLOCS))

    assert resp.status_code == 200
    assert "motif_modification" in resp.context["adminform"].form.errors
    pc.refresh_from_db()
    assert pc.blocs != BLOCS
    assert len(_revisions("pc_h4")) == 1


def test_admin_une_seule_revision_avec_composants_de_fusion(admin_client):
    client, _ = admin_client
    pc1 = CodePrescription.objects.create(identifiant="pc_h_a", texte_court="t")
    fusion = CodePrescription.objects.create(identifiant="pc_h_fusion", texte_court="t")

    _post_pc(
        client,
        fusion,
        composants_fusion=[pc1.pk],
        mots_cles="fusion",
        motif_modification="création de la fusion",
    )

    revs = _revisions("pc_h_fusion")
    assert len(revs) == 2
    assert revs[-1].champs_modifies == ["composants_fusion", "mots_cles"]
    assert revs[-1].instantane["composants_fusion"] == ["pc_h_a"]


def test_composants_hors_admin_traces():
    pc1 = CodePrescription.objects.create(identifiant="pc_h_b", texte_court="t")
    fusion = CodePrescription.objects.create(identifiant="pc_h_f2", texte_court="t")
    fusion.composants_fusion.add(pc1)
    assert _revisions("pc_h_f2")[-1].instantane["composants_fusion"] == ["pc_h_b"]


def test_suppression_garde_le_dernier_etat():
    pc = CodePrescription.objects.create(
        identifiant="pc_h5", texte_court="t", blocs=BLOCS
    )
    pc.delete()
    rev = _revisions("pc_h5")[-1]
    assert rev.action == RevisionContenu.ACTION_SUPPRESSION
    assert rev.instantane["blocs"] == BLOCS


def test_contexte_differe_une_revision_sur_etat_final():
    with historique.contexte_revision(
        origine=RevisionContenu.ORIGINE_COMMANDE, motif="propagation", differer=True
    ):
        pc = CodePrescription.objects.create(identifiant="pc_h6", texte_court="t")
        pc.blocs = BLOCS
        pc.save()
        CodePrescription.objects.filter(pk=pc.pk).update(mots_cles="final")

    revs = _revisions("pc_h6")
    assert len(revs) == 1
    assert revs[0].instantane["mots_cles"] == "final"
    assert revs[0].motif == "propagation"


def test_motif_par_variable_d_environnement(monkeypatch):
    monkeypatch.setenv("NITRATES_MOTIF_REVISION", "copié depuis dev")
    CodePrescription.objects.create(identifiant="pc_h7", texte_court="t")
    assert _revisions("pc_h7")[0].motif == "copié depuis dev"


def test_constat_detecte_un_update_sans_trace():
    pc = CodePrescription.objects.create(identifiant="pc_h8", texte_court="t")
    CodePrescription.objects.filter(pk=pc.pk).update(blocs=BLOCS)
    assert len(_revisions("pc_h8")) == 1

    call_command("constater_historique_contenus", verbosity=0)
    rev = _revisions("pc_h8")[-1]
    assert rev.action == RevisionContenu.ACTION_CONSTAT
    assert rev.champs_modifies == ["blocs"]

    call_command("constater_historique_contenus", verbosity=0)
    assert len(_revisions("pc_h8")) == 2


def test_constat_pose_l_etat_initial_et_les_suppressions_sans_trace():
    pc = CodePrescription.objects.create(identifiant="pc_h9", texte_court="t")
    RevisionContenu.objects.filter(identifiant="pc_h9").delete()
    call_command("constater_historique_contenus", verbosity=0)
    assert _revisions("pc_h9")[0].action == RevisionContenu.ACTION_CREATION

    CodePrescription.objects.filter(pk=pc.pk)._raw_delete(CodePrescription.objects.db)
    call_command("constater_historique_contenus", verbosity=0)
    assert _revisions("pc_h9")[-1].action == RevisionContenu.ACTION_SUPPRESSION


def test_seed_referentiels_idempotent_dans_l_historique():
    call_command("seed_referentiels", verbosity=0)
    avant = RevisionContenu.objects.count()
    call_command("seed_referentiels", verbosity=0)
    assert RevisionContenu.objects.count() == avant


def test_contenu_rich_trace():
    c = ContenuRichDSFR.objects.create(cle="page.test-historique", libelle_admin="x")
    c.blocs = BLOCS
    c.save()
    revs = _revisions("page.test-historique", RevisionContenu.TYPE_CONTENU_RICH)
    assert [r.champs_modifies for r in revs][-1] == ["blocs"]


def test_textes_rendus_inclut_les_sous_puces():
    assert textes_rendus(BLOCS) == [
        "# Conditions",
        "    • les conditions du PAR, notamment sur :",
        "        ◦ la durée du couvert",
    ]


def test_pages_admin_historique(admin_client):
    client, _ = admin_client
    pc = CodePrescription.objects.create(identifiant="pc_h10", texte_court="t")
    pc.blocs = BLOCS
    pc.save()
    rev = _revisions("pc_h10")[-1]

    fiche = client.get(reverse("admin:nitrates_codeprescription_change", args=[pc.pk]))
    assert (
        reverse("admin:nitrates_revisioncontenu_change", args=[rev.pk])
        in fiche.content.decode()
    )

    detail = client.get(reverse("admin:nitrates_revisioncontenu_change", args=[rev.pk]))
    html = detail.content.decode()
    assert detail.status_code == 200
    assert "la durée du couvert" in html
    assert "révision précédente" in html

    liste = client.get(reverse("admin:nitrates_revisioncontenu_changelist"))
    assert liste.status_code == 200


# ─── Garde-fou : l'éditeur ne doit plus jamais supprimer de sous-puces ───────


def _sans_sous_puces(blocs):
    """Ce que renvoie l'éditeur admin après un simple « Enregistrer »."""
    copie = json.loads(json.dumps(blocs))
    for bloc in copie["blocs"]:
        for item in bloc.get("data", {}).get("items", []) or []:
            item.pop("enfants", None)
    return copie


def test_admin_refuse_un_enregistrement_qui_perd_des_sous_puces(admin_client):
    client, _ = admin_client
    pc = CodePrescription.objects.create(
        identifiant="pc_h11", texte_court="t", blocs=BLOCS
    )

    resp = _post_pc(
        client,
        pc,
        blocs=json.dumps(_sans_sous_puces(BLOCS)),
        motif_modification="simple relecture",
    )

    assert resp.status_code == 200
    erreurs = resp.context["adminform"].form.errors["blocs"]
    assert "la durée du couvert" in erreurs[0]
    pc.refresh_from_db()
    assert pc.blocs == BLOCS
    assert len(_revisions("pc_h11")) == 1


def test_garde_fou_laisse_supprimer_la_puce_parente():
    from envergo.nitrates.admin import verifier_sous_puces_conservees

    sans_la_liste = {"schema": 1, "blocs": BLOCS["blocs"][:1]}
    verifier_sous_puces_conservees(BLOCS, sans_la_liste)
    verifier_sous_puces_conservees(BLOCS, BLOCS)


def test_garde_fou_sur_les_contenus_riches():
    from django import forms

    from envergo.nitrates.admin import ContenuRichDSFRForm

    c = ContenuRichDSFR.objects.create(
        cle="page.sous-puces", libelle_admin="x", blocs=BLOCS
    )
    form = ContenuRichDSFRForm(
        data={
            "cle": c.cle,
            "libelle_admin": "x",
            "blocs": json.dumps(_sans_sous_puces(BLOCS)),
            "type_contenu": c.type_contenu,
            "motif_modification": "relecture",
        },
        instance=c,
    )
    assert not form.is_valid()
    assert "blocs" in form.errors
    assert isinstance(form.errors.as_data()["blocs"][0], forms.ValidationError)


def test_seed_contenus_rich_preserve_les_editions_admin():
    call_command("seed_contenus_rich", verbosity=0)
    c = ContenuRichDSFR.objects.get(cle="resultat.regles_permanentes")
    c.blocs = BLOCS
    c.save()

    call_command("seed_contenus_rich", verbosity=0)
    c.refresh_from_db()
    assert c.blocs == BLOCS

    call_command(
        "seed_contenus_rich", ecraser=True, motif="retour au YAML", verbosity=0
    )
    c.refresh_from_db()
    assert c.blocs != BLOCS
    rev = _revisions(c.cle, RevisionContenu.TYPE_CONTENU_RICH)[-1]
    assert rev.motif == "retour au YAML"
    assert rev.source.startswith("seed_contenus_rich")
