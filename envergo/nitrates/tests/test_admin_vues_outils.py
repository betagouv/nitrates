"""Vues admin outils : aperçu des contenus riches (#136), mini-browser des
arbres YAML, consultation des rapports Nuclei (local uniquement, #97)."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from envergo.nitrates import views_admin_nuclei
from envergo.nitrates.models import CodePrescription, ContenuRichDSFR, DecisionTree

pytestmark = pytest.mark.django_db

BLOCS = [{"type": "paragraphe", "data": {"texte": "Texte de test"}}]


def _url(nom, **kwargs):
    # urlconf nitrates posé par le middleware, pas le ROOT_URLCONF des tests.
    return reverse(nom, kwargs=kwargs or None, urlconf="config.urls_nitrates")


@pytest.fixture
def staff_client(client):
    u = get_user_model().objects.create_user(
        email="outils@test.local", name="Outils", password="x", is_staff=True
    )
    client.force_login(u)
    return client


# --- aperçu contenu riche ---------------------------------------------------

PREVIEW = "nitrates_admin_contenu_rich_preview"


def test_preview_pc_par_identifiant_et_par_pk(staff_client):
    pc = CodePrescription.objects.create(
        identifiant="pc_preview", mots_cles="reliquats", blocs=BLOCS
    )

    for ident in ("pc_preview", str(pc.pk)):
        r = staff_client.get(_url(PREVIEW), {"type": "pc", "id": ident})
        assert r.status_code == 200
        assert r.context["titre_preview"] == "PC PC_PREVIEW — reliquats"
        assert "Texte de test" in r.context["contenu_html"]


def test_preview_contenu_riche_par_cle_et_par_pk(staff_client):
    c = ContenuRichDSFR.objects.create(
        cle="page_preview", libelle_admin="Page", blocs=BLOCS
    )

    for ident in ("page_preview", str(c.pk)):
        r = staff_client.get(_url(PREVIEW), {"type": "rich", "id": ident})
        assert r.status_code == 200
        assert r.context["titre_preview"] == "page_preview — Page"


@pytest.mark.parametrize(
    "params",
    [
        {"type": "pc", "id": "inexistante"},
        {"type": "rich", "id": "999999"},
        {"type": "autre", "id": "1"},
    ],
)
def test_preview_404(staff_client, params):
    assert staff_client.get(_url(PREVIEW), params).status_code == 404


def test_preview_reserve_au_staff(client):
    r = client.get(_url(PREVIEW), {"type": "pc", "id": "pc1"})
    assert r.status_code == 302


# --- mini-browser YAML ------------------------------------------------------


def test_yaml_browser_liste_actif_puis_brouillons_puis_archives(staff_client):
    archive = DecisionTree.objects.create(
        name="a", status=DecisionTree.STATUS_ARCHIVE, contenu={}
    )
    draft = DecisionTree.objects.create(
        name="d", status=DecisionTree.STATUS_DRAFT, contenu={}
    )
    actif = DecisionTree.objects.create(
        name="z",
        status=DecisionTree.STATUS_ACTIVE,
        scope=DecisionTree.SCOPE_REGION,
        region_code="99",
        contenu={},
    )

    r = staff_client.get(_url("nitrates_yaml_browser_list"))

    noms = [t.name for t in r.context["trees"] if t in (archive, draft, actif)]
    assert noms == ["z", "d", "a"]


def test_yaml_browser_detail(staff_client):
    tree = DecisionTree.objects.create(
        name="t",
        status=DecisionTree.STATUS_DRAFT,
        contenu={},
        contenu_yaml_brut="arbre:\n  noeud: {}\n",
    )

    r = staff_client.get(_url("nitrates_yaml_browser_detail", pk=tree.pk))

    assert r.status_code == 200
    assert r.context["lines"] == 3


def test_yaml_browser_detail_introuvable(staff_client):
    r = staff_client.get(_url("nitrates_yaml_browser_detail", pk=999999))
    assert r.status_code == 404


# --- rapports Nuclei --------------------------------------------------------


@pytest.fixture
def rapports(settings, monkeypatch, tmp_path):
    settings.DEBUG = True
    dossier = tmp_path / "nuclei_reports"
    monkeypatch.setattr(views_admin_nuclei, "REPORTS_DIR", dossier)
    for stamp in ("20260101-000000", "20260201-000000"):
        (dossier / stamp).mkdir(parents=True)
        (dossier / stamp / "report.html").write_text(f"<p>{stamp}</p>")
    (dossier / "incomplet").mkdir()
    return dossier


def test_nuclei_index_liste_les_runs_du_plus_recent(staff_client, rapports):
    r = staff_client.get(_url("nitrates_admin_nuclei_index"))
    assert [run["name"] for run in r.context["runs"]] == [
        "20260201-000000",
        "20260101-000000",
    ]


def test_nuclei_report_latest_et_par_stamp(staff_client, rapports):
    r = staff_client.get(_url("nitrates_admin_nuclei_report", stamp="latest"))
    assert b"20260201-000000" in r.content
    r = staff_client.get(_url("nitrates_admin_nuclei_report", stamp="20260101-000000"))
    assert b"20260101-000000" in r.content


@pytest.mark.parametrize("stamp", ["incomplet", "inexistant", ".."])
def test_nuclei_report_introuvable_ou_traversal(staff_client, rapports, stamp):
    r = staff_client.get(_url("nitrates_admin_nuclei_report", stamp=stamp))
    assert r.status_code == 404


def test_nuclei_sans_rapport(staff_client, settings, monkeypatch, tmp_path):
    settings.DEBUG = True
    monkeypatch.setattr(views_admin_nuclei, "REPORTS_DIR", tmp_path / "absent")
    r = staff_client.get(_url("nitrates_admin_nuclei_index"))
    assert r.context["has_reports"] is False
    r = staff_client.get(_url("nitrates_admin_nuclei_report", stamp="latest"))
    assert r.status_code == 404


def test_nuclei_invisible_hors_local(staff_client, rapports, settings):
    settings.DEBUG = False
    assert staff_client.get(_url("nitrates_admin_nuclei_index")).status_code == 404
    r = staff_client.get(_url("nitrates_admin_nuclei_report", stamp="latest"))
    assert r.status_code == 404
