"""Tests du templatetag `calendrier_epandage`."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from envergo.nitrates.templatetags.nitrates_tags import (
    _day_of_year,
    _segment_interdit,
    calendrier_epandage,
    est_interdit_toute_lannee,
)

# La fixture session `update_default_site` (envergo/conftest.py) cree un
# Site testserver et necessite l'acces DB. On opt-in.
pytestmark = pytest.mark.django_db


# ─── Helpers internes ──────────────────────────────────────────────────────


def test_day_of_year_basique_annee_agricole():
    """L'annee agricole commence le 1er juillet (jour 0)."""
    assert _day_of_year(1, 7) == 0
    assert _day_of_year(30, 6) == 364
    # 1er janvier = 6 mois apres juillet (juil + aout + sep + oct + nov + dec)
    assert _day_of_year(1, 1) == 31 + 31 + 30 + 31 + 30 + 31  # 184


def test_segment_interdit_centre_annee_agricole():
    """Periode 15/12 -> 15/01 traverse l'annee CIVILE mais pas l'annee
    AGRICOLE -> 1 seul segment continu, centre sur la barre."""
    segs = _segment_interdit({"du": "15/12", "au": "15/01"})
    assert len(segs) == 1


def test_segment_interdit_simple():
    """Periode 15/12 -> 25/12 : 1 segment dans le meme mois."""
    segs = _segment_interdit({"du": "15/12", "au": "25/12"})
    assert len(segs) == 1
    start, width = segs[0]
    # 15/12 -> 25/12 = 11 jours
    assert width == pytest.approx(11 / 365 * 100, abs=0.01)


def test_segment_interdit_pivot_annee_agricole():
    """Periode qui traverse le 30 juin (pivot de l'annee agricole) ->
    2 segments. Ex : 15/05 -> 15/08 (mai puis aout)."""
    segs = _segment_interdit({"du": "15/05", "au": "15/08"})
    assert len(segs) == 2


def test_segment_interdit_phenologique():
    """Une borne phenologique avec date_calendrier en DB produit un vrai
    segment. Sans date_calendrier (ou evenement inconnu), retombe sur
    une liste vide."""
    # `brunissement_des_soies` a `date_calendrier: "15/08"` en DB,
    # donc on produit un segment 15/08 -> 15/02.
    segs = _segment_interdit({"du": "brunissement_des_soies", "au": "15/02"})
    assert len(segs) >= 1, "Borne phenologique connue doit produire un segment"
    # Evenement inexistant : pas de date_calendrier -> liste vide.
    segs = _segment_interdit({"du": "evenement_inexistant", "au": "15/02"})
    assert segs == []


# ─── Templatetag ───────────────────────────────────────────────────────────


def _regle(**kwargs):
    """Helper : construit un objet ressemblant a un Resultat."""
    defaults = {"type": "interdiction", "periodes": [{"du": "15/12", "au": "15/01"}]}
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_calendrier_avec_regle_none():
    ctx = calendrier_epandage(None)
    assert ctx["vide"] is True


def test_calendrier_interdiction_genere_segments():
    """Une regle d'interdiction sur 15/12 -> 15/01 doit produire 1 segment
    rouge centre (annee agricole juil->juin, le 31/12 n'est pas le pivot)."""
    ctx = calendrier_epandage(
        _regle(type="interdiction", periodes=[{"du": "15/12", "au": "15/01"}])
    )
    assert ctx["vide"] is False
    assert ctx["fond"] == "vert"
    assert len(ctx["segments"]) == 1
    assert ctx["segments"][0]["couleur"] == "rouge"
    # Note 2026-05-12 : tous les types epandage utilisent un label
    # commun "Calendrier d'épandage" (UX validee par Max).
    assert "Calendrier" in ctx["label"]


def test_calendrier_segment_porte_un_tooltip():
    """Chaque segment expose un tooltip humain au survol (#134) : verbe de
    regime + phrase de bornes, comme le calendrier dynamique."""
    ctx = calendrier_epandage(
        _regle(type="interdiction", periodes=[{"du": "15/12", "au": "15/01"}])
    )
    seg = ctx["segments"][0]
    assert seg["tooltip"].startswith("Interdit")
    assert "15" in seg["tooltip"]


def test_calendrier_tooltip_orange_sous_condition():
    """Zone orange -> tooltip 'Autorisé sous conditions ...'."""
    ctx = calendrier_epandage(
        _regle(
            type="autorisation_sous_condition",
            periodes=[{"du": "15/12", "au": "15/01"}],
        )
    )
    seg = ctx["segments"][0]
    assert seg["couleur"] == "orange"
    assert seg["tooltip"].startswith("Autorisé sous conditions")


def test_calendrier_libre_pas_de_zone_overlay():
    """Une regle 'libre' n'a pas de periode interdite : pas de zone overlay."""
    ctx = calendrier_epandage(_regle(type="libre", periodes=[]))
    assert ctx["fond"] == "vert"
    assert ctx["segments"] == []
    # Label unifie "Calendrier d'épandage" pour tous les types epandage.
    assert ctx["label"] == "Calendrier d'épandage"


def test_calendrier_non_applicable_fond_gris():
    ctx = calendrier_epandage(_regle(type="non_applicable", periodes=[]))
    assert ctx["fond"] == "gris"
    assert ctx["label"] == "Ne s'applique pas"


def test_calendrier_plafonnement_overlay_orange():
    ctx = calendrier_epandage(
        _regle(type="plafonnement", periodes=[{"du": "01/03", "au": "31/05"}])
    )
    assert len(ctx["segments"]) == 1
    assert ctx["segments"][0]["couleur"] == "orange"
    # Label unifie pour tous les types epandage (cf. UX 2026-05-12).
    assert ctx["label"] == "Calendrier d'épandage"


def test_calendrier_phenologique_dans_liste_a_part():
    """Une periode dont la borne est un evenement phenologique CONNU
    (avec date_calendrier dans referentiels.yaml) genere maintenant un
    vrai segment via la date conventionnelle (changement UX 2026-05-12 :
    on affiche les fenetres phenologiques en hachure orange dans la barre).
    Pour les evenements INCONNUS (typo, slug pas dans le referentiel), on
    fallback sur periodes_phenologiques (texte a part)."""
    # Evenement connu -> segment direct (sans liste phenologique).
    ctx = calendrier_epandage(
        _regle(
            type="interdiction",
            periodes=[{"du": "brunissement_des_soies", "au": "15/02"}],
        )
    )
    assert len(ctx["segments"]) >= 1
    assert ctx["segments"][0]["is_flottant"] is True

    # Evenement inconnu -> retombe sur periodes_phenologiques.
    ctx2 = calendrier_epandage(
        _regle(
            type="interdiction",
            periodes=[{"du": "evenement_inexistant", "au": "15/02"}],
        )
    )
    assert ctx2["segments"] == []
    assert len(ctx2["periodes_phenologiques"]) == 1


def test_calendrier_borne_phenologique_couleur_et_encadre():
    """#107 : une borne phenologique (ex derniere coupe luzerne) qui ouvre une
    zone d'autorisation sous condition prend la couleur ORANGE de sa zone (pas
    du noir) et porte un `date_exemple` (« Ici exemple au <date> ») = sa date
    conventionnelle. Pour une zone d'interdiction, la borne serait rouge."""
    # Regle type mixte : interdiction 15/12->15/01 + ASC derniere coupe->15/01.
    ctx = calendrier_epandage(
        _regle(
            type="mixte",
            periodes=[
                {"du": "15/12", "au": "15/01", "regime": "interdiction"},
                {
                    "du": "derniere_coupe_luzerne",
                    "au": "15/01",
                    "regime": "autorisation_sous_condition",
                },
            ],
        )
    )
    bornes = ctx["bornes"]
    pheno = [b for b in bornes if b.get("is_phenologique")]
    assert pheno, "la borne phenologique doit etre exposee"
    b = pheno[0]
    # Couleur de la zone ASC ouverte par la coupe = orange (pas noir).
    assert b["couleur"] == "orange"
    # Sous-texte « Ici exemple au <date> » = date_calendrier lisible.
    assert b["date_exemple"], "date_exemple attendu pour la borne phenologique"
    assert "décembre" in b["date_exemple"] or "janvier" in b["date_exemple"]
    # Le libelle reste le libelle public lisible (pas le slug).
    assert "coupe" in b["label"].lower()


def test_calendrier_borne_fixe_pas_dencadre():
    """Une borne fixe (JJ/MM) ne porte ni couleur de zone ni date_exemple :
    pas d'encadre, comportement inchange (#107)."""
    ctx = calendrier_epandage(
        _regle(type="interdiction", periodes=[{"du": "15/12", "au": "15/01"}])
    )
    for b in ctx["bornes"]:
        assert not b.get("is_phenologique")
        assert b.get("date_exemple") is None
        assert b.get("couleur") is None


def test_calendrier_marqueur_today_present():
    """today_pct doit etre dans [0, 100]."""
    ctx = calendrier_epandage(_regle())
    assert 0 <= ctx["today_pct"] <= 100


def test_calendrier_today_pct_calcule_correctement():
    """En patchant la date du jour, on verifie le calcul du today_pct
    en annee agricole (juil = 0)."""
    with patch("envergo.nitrates.templatetags.nitrates_tags.date") as mock_date:
        mock_date.today.return_value = date(2026, 7, 1)  # 1er juillet
        ctx = calendrier_epandage(_regle())
        # 1er juillet = jour 0 de l'annee agricole
        assert ctx["today_pct"] == pytest.approx(0, abs=0.1)


def test_calendrier_bornes_pour_dates_limites():
    """Les bornes de chaque periode parsable sont exposees pour affichage."""
    ctx = calendrier_epandage(
        _regle(type="interdiction", periodes=[{"du": "15/12", "au": "15/01"}])
    )
    labels = [b["label"] for b in ctx["bornes"]]
    assert "15/12" in labels
    assert "15/01" in labels


def test_calendrier_a_completer_fond_gris():
    ctx = calendrier_epandage(_regle(type="a_completer", periodes=[]))
    assert ctx["fond"] == "gris"


def test_calendrier_calculatrice_orange():
    ctx = calendrier_epandage(_regle(type="calculatrice", periodes=[]))
    assert ctx["fond"] == "orange"
    assert ctx["label"] == "Calcul nécessaire"


def test_calendrier_12_mois_annee_agricole():
    """L'ordre des mois suit l'annee agricole (juil debut, juin fin)."""
    ctx = calendrier_epandage(_regle())
    assert len(ctx["mois"]) == 12
    # Chaque entree est une paire (label 3 lettres, initiale) : l'initiale sert
    # a l'affichage mobile 1 lettre (#177). Labels alignes sur le calendrier
    # dynamique (#134) : "Jui" pour juin.
    assert ctx["mois"][0] == ("Juil", "J")
    assert ctx["mois"][-1] == ("Jui", "J")


def test_calendrier_regime_mixte_par_periode():
    """Une regle a regime mixte (cf. colza Type III note_5 du 30/04) :
    1ere periode `autorisation_sous_condition` (orange), 2e periode
    `interdiction` (rouge). Le `type` global de la regle est utilise
    comme fallback uniquement si la periode n'a pas de `regime`."""
    ctx = calendrier_epandage(
        _regle(
            type="interdiction",
            periodes=[
                {
                    "du": "01/09",
                    "au": "15/10",
                    "regime": "autorisation_sous_condition",
                },
                {"du": "15/10", "au": "15/01", "regime": "interdiction"},
            ],
        )
    )
    assert len(ctx["segments"]) == 2
    couleurs = [s["couleur"] for s in ctx["segments"]]
    assert couleurs == ["orange", "rouge"]


def test_calendrier_regime_periode_prime_sur_type_global():
    """Si une regle est de type `interdiction` mais qu'une de ses
    periodes a `regime: libre`, ce segment ne doit pas s'afficher
    (libre = etat de fond, pas d'overlay)."""
    ctx = calendrier_epandage(
        _regle(
            type="interdiction",
            periodes=[
                {"du": "01/09", "au": "15/10", "regime": "libre"},
                {
                    "du": "15/10",
                    "au": "15/01",
                },  # pas de regime -> fallback interdiction
            ],
        )
    )
    # 1 seul segment rouge (le 2e), pas de segment pour le 1er (libre)
    assert len(ctx["segments"]) == 1
    assert ctx["segments"][0]["couleur"] == "rouge"


# ─── est_interdit_toute_lannee (#85) ────────────────────────────────────────


def test_toute_lannee_vrai_pour_interdiction_01_07_30_06():
    r = _regle(type="interdiction", periodes=[{"du": "01/07", "au": "30/06"}])
    assert est_interdit_toute_lannee(r) is True


def test_toute_lannee_faux_pour_interdiction_hivernale():
    # Colza type_II : interdiction 15/12 -> 15/01, pas toute l'annee.
    r = _regle(type="interdiction", periodes=[{"du": "15/12", "au": "15/01"}])
    assert est_interdit_toute_lannee(r) is False


def test_toute_lannee_faux_si_regle_none():
    assert est_interdit_toute_lannee(None) is False


def test_toute_lannee_faux_si_autre_periode_presente():
    # Une interdiction pleine annee MAIS avec une autre periode -> pas "toute
    # l'annee" au sens simple (le calendrier nuance).
    r = _regle(
        type="mixte",
        periodes=[
            {"du": "01/07", "au": "30/06", "regime": "interdiction"},
            {"du": "15/12", "au": "15/01", "regime": "autorisation_sous_condition"},
        ],
    )
    assert est_interdit_toute_lannee(r) is False


def test_calendrier_borne_phenologique_label_resolu():
    """Le label du tick d'une borne phenologique est resolu vers son
    libelle_public lisible, pas le slug snake_case (#85)."""
    ctx = calendrier_epandage(
        _regle(
            type="mixte",
            periodes=[
                {"du": "15/12", "au": "15/01", "regime": "interdiction"},
                {
                    "du": "derniere_coupe_luzerne",
                    "au": "15/01",
                    "regime": "autorisation_sous_condition",
                },
            ],
        )
    )
    labels = [b["label"] for b in ctx["bornes"]]
    assert "Dernière coupe de la luzerne" in labels
    assert "derniere_coupe_luzerne" not in labels


def test_calendrier_asc_sans_periode_peint_toute_lannee():
    """ASC sans aucune periode = "sous condition toute l'annee" (regles
    partagees CIE/CINE courte, type III, plafonnements). Le calendrier doit
    synthetiser une periode pleine annee -> overlay orange + legende "Autorise
    sous condition", au lieu d'un fond vert trompeur "Autorise" (fix Max
    2026-06-18)."""
    ctx = calendrier_epandage(_regle(type="autorisation_sous_condition", periodes=None))
    # Au moins un segment orange couvrant l'annee.
    assert ctx["segments"], "aucun segment peint (fond vert trompeur)"
    assert any(s["couleur"] == "orange" for s in ctx["segments"])
    # Legende : "Autorise sous condition" present, pas seulement "Autorise".
    labels = [item["label"] for item in ctx["legende"]]
    assert any("sous condition" in label for label in labels)


def test_calendrier_autorisation_simple_sans_periode_reste_verte():
    """Garde-fou : une autorisation PURE (type "autorisation" ou "libre") sans
    periode ne doit PAS etre repeinte en orange -- seuls ASC / plafonnement le
    sont. Le cas 99% (autorise librement) reste vert."""
    ctx = calendrier_epandage(_regle(type="libre", periodes=None))
    assert all(s["couleur"] != "orange" for s in ctx["segments"])


# ─── PC plafond : coloration verte quand une regle est 100% plafond (CR 2026-08)

# Referentiel minimal : pc12/pc13 sont des plafonds, pc1 non.
_REF_PLAFOND = {
    "pc12": {"plafond": True},
    "pc13": {"plafond": True},
    "pc1": {"texte_court": "vraie PC conditionnee"},
}


def test_regle_uniquement_plafonds():
    from envergo.nitrates.templatetags.nitrates_tags import regle_uniquement_plafonds

    assert regle_uniquement_plafonds(
        _regle(codes_prescription=["pc12", "pc13"]), _REF_PLAFOND
    )
    # une seule vraie PC suffit a casser le 100% plafond
    assert not regle_uniquement_plafonds(
        _regle(codes_prescription=["pc12", "pc1"]), _REF_PLAFOND
    )
    # aucune PC -> pas "uniquement plafonds"
    assert not regle_uniquement_plafonds(_regle(codes_prescription=[]), _REF_PLAFOND)


def test_calendrier_regle_tout_plafond_asc_peinte_verte():
    """Regle dont TOUTES les PC sont des plafonds : sa periode ASC devient une
    periode autorisee -> aucun overlay orange (fond vert)."""
    regle = _regle(
        type="autorisation_sous_condition",
        codes_prescription=["pc12", "pc13"],
        periodes=[
            {"du": "01/09", "au": "31/01", "regime": "autorisation_sous_condition"}
        ],
    )
    ctx = calendrier_epandage(regle, _REF_PLAFOND)
    assert all(s["couleur"] != "orange" for s in ctx["segments"])


def test_calendrier_regle_plafond_mixte_reste_orange():
    """Regle avec une PC plafond ET une vraie PC : la periode ASC reste orange
    (le plafond ne suffit pas a tout autoriser)."""
    regle = _regle(
        type="autorisation_sous_condition",
        codes_prescription=["pc12", "pc1"],
        periodes=[
            {"du": "01/09", "au": "31/01", "regime": "autorisation_sous_condition"}
        ],
    )
    ctx = calendrier_epandage(regle, _REF_PLAFOND)
    assert any(s["couleur"] == "orange" for s in ctx["segments"])


def test_periodes_par_section_tout_plafond_asc_devient_autorisation():
    """La section recap : une regle 100% plafond ne montre PAS de section
    "autorisation sous condition" -- ses periodes rejoignent "Autorisé"."""
    from envergo.nitrates.templatetags.nitrates_tags import periodes_par_section

    regle = _regle(
        type="autorisation_sous_condition",
        codes_prescription=["pc12", "pc13"],
        texte_condition=None,
        periodes=[
            {"du": "01/09", "au": "31/01", "regime": "autorisation_sous_condition"}
        ],
    )
    titres = [s["titre"] for s in periodes_par_section(regle, _REF_PLAFOND)]
    assert "Période d’autorisation sous condition" not in titres
    assert "Période d’autorisation" in titres


def test_drawer_conditions_masque_si_que_plafonds():
    """Le drawer conditions n'a pas de contenu si la regle n'a que des PC
    plafond (elles s'affichent inline, pas dans le drawer)."""
    from envergo.nitrates.templatetags.nitrates_tags import (
        drawer_conditions_a_du_contenu,
    )

    regle_plafond = _regle(codes_prescription=["pc12", "pc13"], note=None)
    regle_mixte = _regle(codes_prescription=["pc12", "pc1"], note=None)
    assert not drawer_conditions_a_du_contenu(regle_plafond, _REF_PLAFOND)
    assert drawer_conditions_a_du_contenu(regle_mixte, _REF_PLAFOND)


def test_calculatrice_data_json_expose_plafond():
    """Le JSON calculatrice expose codes_prescription_plafond + tous_plafonds
    pour piloter le calendrier dynamique cote JS."""
    from envergo.nitrates.templatetags.nitrates_tags import calculatrice_data_json

    regle = _regle(codes_prescription=["pc12", "pc13"])
    # _regle est un SimpleNamespace : on lui donne un to_json_dict minimal.
    regle.to_json_dict = lambda: {
        "regle_id": "x",
        "type": regle.type,
        "periodes": regle.periodes,
        "codes_prescription": regle.codes_prescription,
    }
    data = calculatrice_data_json(regle, _REF_PLAFOND)
    assert data["tous_plafonds"] is True
    assert set(data["codes_prescription_plafond"]) == {"pc12", "pc13"}


# ─── #186 : fermeture des bords de la barre + labels de bornes extremes ────
#
# La metier a signale des "contours gauche/droite absents" sur le calendrier.
# Cause : une zone adossee a un bord de la barre dessine un rectangle a angles
# droits qui deborde l'arrondi de la barre, et depuis #132/#134 les zones n'ont
# plus de bordure laterale (chaque frontiere INTERNE est materialisee par le tic
# de sa borne). Aux extremites de l'annee agricole (01/07 et 30/06) il n'y a pas
# de borne -> plus rien ne referme le segment.
# Meme famille de bug pour le LABEL d'une borne posee sur une extremite :
# centre via translateX(-50%), il sortait du conteneur et etait coupe
# ("/07" au lieu de "01/07").
# Ces flags sont consommes par calendrier.css (--bord-gauche / --bord-droit).


def test_segment_demarrant_au_1er_juillet_est_marque_bord_gauche():
    """01/07 = jour 0 de l'annee agricole -> le segment touche le bord gauche."""
    ctx = calendrier_epandage(
        _regle(type="interdiction", periodes=[{"du": "01/07", "au": "15/01"}])
    )
    seg = ctx["segments"][0]
    assert seg["start_pct"] == pytest.approx(0, abs=0.01)
    assert seg["bord_gauche"] is True
    assert seg["bord_droit"] is False


def test_segment_finissant_au_30_juin_est_marque_bord_droit():
    """30/06 = dernier jour de l'annee agricole -> bord droit."""
    ctx = calendrier_epandage(
        _regle(type="interdiction", periodes=[{"du": "15/01", "au": "30/06"}])
    )
    seg = ctx["segments"][0]
    assert seg["start_pct"] + seg["width_pct"] == pytest.approx(100, abs=0.01)
    assert seg["bord_gauche"] is False
    assert seg["bord_droit"] is True


def test_segment_pleine_annee_est_marque_des_deux_bords():
    """Interdiction 01/07 -> 30/06 : la zone couvre toute la barre, elle doit
    etre fermee et arrondie des DEUX cotes (capture 4 du ticket #186)."""
    ctx = calendrier_epandage(
        _regle(type="interdiction", periodes=[{"du": "01/07", "au": "30/06"}])
    )
    seg = ctx["segments"][0]
    assert seg["bord_gauche"] is True
    assert seg["bord_droit"] is True


def test_segment_au_milieu_nest_marque_aucun_bord():
    """Non-regression : une zone interne ne doit PAS recuperer de bordure
    laterale, sinon on reintroduit le double-trait corrige en #132/#134
    (bordure de zone + tic de borne, jamais pile alignes)."""
    ctx = calendrier_epandage(
        _regle(type="interdiction", periodes=[{"du": "15/12", "au": "15/01"}])
    )
    for seg in ctx["segments"]:
        assert seg["bord_gauche"] is False
        assert seg["bord_droit"] is False


def test_segment_demarrant_au_2_juillet_nest_pas_colle_au_bord():
    """Garde-fou sur l'epsilon : 1 jour d'ecart (~0.27%) ne doit pas etre
    confondu avec un segment reellement adosse au bord."""
    ctx = calendrier_epandage(
        _regle(type="interdiction", periodes=[{"du": "02/07", "au": "15/01"}])
    )
    assert ctx["segments"][0]["bord_gauche"] is False


def test_pivot_annee_agricole_marque_les_deux_bords_separement():
    """Periode qui traverse le 30/06 (ex 15/05 -> 15/08) : 2 segments, celui
    de fin d'annee touche le bord DROIT, celui de debut le bord GAUCHE."""
    ctx = calendrier_epandage(
        _regle(type="interdiction", periodes=[{"du": "15/05", "au": "15/08"}])
    )
    segments = ctx["segments"]
    assert len(segments) == 2
    fin_annee, debut_annee = segments
    assert fin_annee["bord_droit"] is True
    assert fin_annee["bord_gauche"] is False
    assert debut_annee["bord_gauche"] is True
    assert debut_annee["bord_droit"] is False


def test_borne_sur_extremite_est_marquee_pour_rabattre_son_label():
    """Une borne au 01/07 est a 0% : son label centre deborderait a gauche.
    Le flag permet au CSS de rabattre la boite en recalant le tic."""
    ctx = calendrier_epandage(
        _regle(type="interdiction", periodes=[{"du": "01/07", "au": "30/06"}])
    )
    par_label = {b["label"]: b for b in ctx["bornes"]}
    assert par_label["01/07"]["bord_gauche"] is True
    assert par_label["01/07"]["bord_droit"] is False
    assert par_label["30/06"]["bord_droit"] is True
    assert par_label["30/06"]["bord_gauche"] is False


def test_borne_interne_nest_pas_rabattue():
    """Non-regression : une borne au milieu garde son centrage sur la date."""
    ctx = calendrier_epandage(
        _regle(type="interdiction", periodes=[{"du": "15/12", "au": "15/01"}])
    )
    for b in ctx["bornes"]:
        assert b["bord_gauche"] is False
        assert b["bord_droit"] is False


# ─── #186 : marqueur "Aujourd'hui" aux extremites (bug A) ──────────────────
#
# Le point est un rond de 9px centre via translate(-50%, -50%) dans une barre
# en overflow:hidden : aux extremites il est coupe de moitie. Le LABEL a ete
# protege en #134 par un clamp() CSS (borne a 37px de chaque bord) ; on verrouille
# ici le contrat cote Python : today_pct reste bien dans [0, 100] et vaut les
# valeurs extremes attendues, c'est le CSS qui absorbe le debordement.


@pytest.mark.parametrize(
    "jour, mois, attendu_pct",
    [
        (1, 7, 0.0),  # tout premier jour de l'annee agricole -> bord gauche
        (30, 6, 364 / 365 * 100),  # tout dernier jour -> bord droit
        (1, 1, 184 / 365 * 100),  # milieu de barre, cas temoin
    ],
)
def test_today_pct_aux_extremites_de_lannee_agricole(jour, mois, attendu_pct):
    """Le point 'Aujourd'hui' doit rester dans la barre quelle que soit la
    date du jour, y compris aux deux extremites (capture 1 du ticket #186)."""
    with patch("envergo.nitrates.templatetags.nitrates_tags.date") as mock_date:
        mock_date.today.return_value = date(2026, mois, jour)
        ctx = calendrier_epandage(_regle())
    assert ctx["today_pct"] == pytest.approx(attendu_pct, abs=0.01)
    assert 0 <= ctx["today_pct"] <= 100


def test_today_pct_est_expose_sans_borne_pour_le_css():
    """Le clamp() qui empeche le point d'etre coupe en deux vit dans le CSS
    (`.calendrier-epandage__today`), pas ici : Python expose la position BRUTE.
    Ce test verrouille ce partage des roles, pour qu'on ne "corrige" pas le
    debordement cote Python en decalant la valeur (ce qui deplacerait le point
    par rapport a la date reelle)."""
    with patch("envergo.nitrates.templatetags.nitrates_tags.date") as mock_date:
        mock_date.today.return_value = date(2026, 7, 1)
        ctx = calendrier_epandage(_regle())
    assert ctx["today_pct"] == pytest.approx(0.0, abs=0.001)
