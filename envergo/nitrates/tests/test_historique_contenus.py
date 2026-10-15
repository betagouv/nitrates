"""Historique des PC et contenus riches (RevisionContenu)."""

import json

import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from envergo.nitrates import historique
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


def test_pages_admin_historique(admin_client):
    client, _ = admin_client
    pc = CodePrescription.objects.create(identifiant="pc_h10", texte_court="t")
    pc.blocs = BLOCS
    pc.save()
    creation, modif = _revisions("pc_h10")
    page = reverse("admin:nitrates_revisioncontenu_historique", args=["pc", "pc_h10"])

    # La fiche résume les dernières versions et mène à la page d'historique.
    fiche = client.get(reverse("admin:nitrates_codeprescription_change", args=[pc.pk]))
    assert page in fiche.content.decode()
    # Le bouton « Historique » standard de la fiche aussi.
    bouton = client.get(
        reverse("admin:nitrates_codeprescription_history", args=[pc.pk])
    )
    assert bouton.status_code == 302 and bouton.url == page
    # L'ancienne page de détail d'une révision redirige vers l'historique.
    detail = client.get(
        reverse("admin:nitrates_revisioncontenu_change", args=[modif.pk])
    )
    assert detail.status_code == 302 and detail.url == f"{page}?a={modif.pk}"

    # Par défaut : la dernière version comparée à la précédente.
    resp = client.get(page)
    html = resp.content.decode()
    assert resp.status_code == 200
    assert resp.context["cible"] == modif and resp.context["base"] == creation
    assert "la durée du couvert" in html
    assert f"type=revision&amp;id={modif.pk}&amp;nu=1" in html

    # Navigation : retour à la fiche, et la version choisie par ?a=.
    assert reverse("admin:nitrates_codeprescription_change", args=[pc.pk]) in html
    resp = client.get(f"{page}?a={creation.pk}")
    assert resp.context["cible"] == creation and resp.context["base"] is None

    liste = client.get(reverse("admin:nitrates_revisioncontenu_changelist"))
    assert liste.status_code == 200


def test_historique_d_un_contenu_supprime_reste_consultable(admin_client):
    client, _ = admin_client
    pc = CodePrescription.objects.create(
        identifiant="pc_h12", texte_court="t", blocs=BLOCS
    )
    pc.delete()
    page = reverse("admin:nitrates_revisioncontenu_historique", args=["pc", "pc_h12"])
    resp = client.get(page)
    assert resp.status_code == 200
    assert "(supprimé)" in resp.content.decode()


def test_resume_signale_les_sous_puces_supprimees():
    from envergo.nitrates.admin_historique import resume_changement

    avant = {"blocs": BLOCS}
    sans = json.loads(json.dumps(BLOCS))
    sans["blocs"][1]["data"]["items"][0].pop("enfants")
    resume, perte = resume_changement(avant, {"blocs": sans})
    assert resume == "1 sous-puce supprimée"
    assert perte is True
    assert resume_changement(None, avant) == ("Version initiale (3 lignes)", False)


def test_diff_mot_a_mot_et_lignes_repliees():
    from envergo.nitrates.admin_historique import grouper, lignes_comparaison

    def para(t):
        return {"type": "paragraphe", "data": {"texte": t}}

    corps = [para(f"ligne {i}") for i in range(10)]
    avant = {
        "blocs": corps + [para("L'épandage est autorisé, le cas échéant, en période.")]
    }
    apres = {
        "blocs": corps + [para("L'épandage est autorisé en période, sous condition.")]
    }
    lignes = lignes_comparaison(avant, apres)
    derniere = lignes[-1]
    assert derniere["genre"] == "modif" and derniere["annulable"] is True
    assert "<del>" in derniere["html"] and "sous condition" in derniere["html"]
    groupes = grouper(lignes)
    assert groupes[0]["pli"] is True and len(groupes[0]["lignes"]) == 8


# ─── Annulation ligne à ligne : nouvelle version par patch inverse ──────────


SANS_SOUS_PUCE = json.loads(json.dumps(BLOCS))
SANS_SOUS_PUCE["blocs"][1]["data"]["items"][0].pop("enfants")


def _page_annulation(client, pc, revision):
    page = reverse(
        "admin:nitrates_revisioncontenu_historique", args=["pc", pc.identifiant]
    )
    return client.get(f"{page}?a={revision.pk}")


def test_annuler_une_ligne_cree_une_nouvelle_version(admin_client):
    client, user = admin_client
    pc = CodePrescription.objects.create(
        identifiant="pc_h20", texte_court="t", blocs=BLOCS
    )
    pc.blocs = SANS_SOUS_PUCE
    pc.save()
    perte = _revisions("pc_h20")[-1]
    resp = _page_annulation(client, pc, perte)
    ligne = next(
        lg
        for g in resp.context["groupes"]
        for lg in g["lignes"]
        if lg["genre"] == "retrait"
    )
    assert ligne["annulable"]

    url = reverse("admin:nitrates_revisioncontenu_annuler", args=["pc", "pc_h20"])
    resp = client.post(
        url,
        {
            "revision": perte.pk,
            "etat": resp.context["etat"],
            "ops": [ligne["op"]],
            "motif": "sous-puce remise",
        },
    )

    assert resp.status_code == 302
    pc.refresh_from_db()
    assert pc.blocs == BLOCS
    revs = _revisions("pc_h20")
    assert len(revs) == 3
    assert revs[-1].motif == "sous-puce remise" and revs[-1].auteur == user
    assert revs[-1].origine == RevisionContenu.ORIGINE_ADMIN


def test_annulation_refusee_si_le_contenu_a_change_depuis(admin_client):
    client, _ = admin_client
    pc = CodePrescription.objects.create(
        identifiant="pc_h21", texte_court="t", blocs=BLOCS
    )
    pc.blocs = SANS_SOUS_PUCE
    pc.save()
    perte = _revisions("pc_h21")[-1]
    resp = _page_annulation(client, pc, perte)
    etat = resp.context["etat"]
    ligne = next(
        lg
        for g in resp.context["groupes"]
        for lg in g["lignes"]
        if lg["genre"] == "retrait"
    )
    pc.mots_cles = "modifié entre-temps"
    pc.save()

    url = reverse("admin:nitrates_revisioncontenu_annuler", args=["pc", "pc_h21"])
    client.post(
        url, {"revision": perte.pk, "etat": etat, "ops": [ligne["op"]], "motif": "x"}
    )

    pc.refresh_from_db()
    assert pc.blocs == SANS_SOUS_PUCE


def test_annuler_une_metadonnee(admin_client):
    client, _ = admin_client
    pc = CodePrescription.objects.create(
        identifiant="pc_h22", texte_court="t", mots_cles="avant"
    )
    pc.mots_cles = "après"
    pc.save()
    rev = _revisions("pc_h22")[-1]
    resp = _page_annulation(client, pc, rev)
    assert [m["champ"] for m in resp.context["metadonnees"] if m["annulable"]] == [
        "mots_cles"
    ]
    url = reverse("admin:nitrates_revisioncontenu_annuler", args=["pc", "pc_h22"])
    client.post(
        url,
        {
            "revision": rev.pk,
            "etat": resp.context["etat"],
            "metas": ["mots_cles"],
            "motif": "retour",
        },
    )
    pc.refresh_from_db()
    assert pc.mots_cles == "avant"


def test_annulation_reservee_a_qui_peut_modifier(db):
    lecteur = User.objects.create(
        email="lecture@test.local", is_staff=True, is_active=True
    )
    from django.contrib.auth.models import Permission

    lecteur.user_permissions.add(
        Permission.objects.get(codename="view_codeprescription")
    )
    client = Client()
    client.force_login(lecteur)
    pc = CodePrescription.objects.create(
        identifiant="pc_h23", texte_court="t", blocs=BLOCS
    )
    pc.blocs = SANS_SOUS_PUCE
    pc.save()
    perte = _revisions("pc_h23")[-1]
    resp = _page_annulation(client, pc, perte)
    assert resp.status_code == 200 and resp.context["peut_annuler"] is False
    url = reverse("admin:nitrates_revisioncontenu_annuler", args=["pc", "pc_h23"])
    resp = client.post(
        url,
        {
            "revision": perte.pk,
            "etat": resp.context["etat"],
            "ops": ["r2"],
            "motif": "x",
        },
    )
    assert resp.status_code == 403
    pc.refresh_from_db()
    assert pc.blocs == SANS_SOUS_PUCE


def test_apercu_d_une_revision_au_rendu_du_site(admin_client):
    client, _ = admin_client
    pc = CodePrescription.objects.create(
        identifiant="pc_h13", texte_court="t", blocs=BLOCS
    )
    rev = _revisions("pc_h13")[-1]
    url = reverse("nitrates_admin_contenu_rich_preview", urlconf="config.urls_nitrates")
    resp = client.get(f"{url}?type=revision&id={rev.pk}&nu=1")
    html = resp.content.decode()
    assert resp.status_code == 200
    assert "la durée du couvert" in html
    assert "dsfr.css" in html and "calendrier.css" in html
    assert pc.identifiant in html


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


def test_apercu_integrable_en_cadre_du_meme_site(admin_client):
    client, _ = admin_client
    CodePrescription.objects.create(identifiant="pc_h14", texte_court="t", blocs=BLOCS)
    rev = _revisions("pc_h14")[-1]
    url = reverse("nitrates_admin_contenu_rich_preview", urlconf="config.urls_nitrates")
    resp = client.get(f"{url}?type=revision&id={rev.pk}&nu=1")
    assert resp["X-Frame-Options"] == "SAMEORIGIN"


def test_liste_numerotee_et_sous_puces_au_rendu():
    from envergo.nitrates.contenu_rich.compilateur import compile_dsfr

    html = compile_dsfr(
        [
            {
                "type": "liste",
                "data": {
                    "style": "ordered",
                    "items": [{"texte": "un", "enfants": [{"texte": "un.a"}]}],
                },
            },
            {"type": "liste", "data": {"items": [{"texte": "puce"}]}},
        ]
    )
    assert '<ol class="fr-mb-0"><li>un<ol><li>un.a</li></ol></li></ol>' in html
    assert '<ul class="fr-mb-0"><li>puce</li></ul>' in html


def test_editeur_actuel_peut_supprimer_une_sous_puce_volontairement(admin_client):
    client, _ = admin_client
    pc = CodePrescription.objects.create(
        identifiant="pc_h30", texte_court="t", blocs=BLOCS
    )
    signe = {**SANS_SOUS_PUCE, "_editeur": "listes-imbriquees"}

    resp = _post_pc(
        client, pc, blocs=json.dumps(signe), motif_modification="sous-puce retirée"
    )

    assert resp.status_code == 302
    pc.refresh_from_db()
    assert pc.blocs == SANS_SOUS_PUCE  # signature retirée avant enregistrement
