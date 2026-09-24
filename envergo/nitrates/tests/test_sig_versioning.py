"""Tests du versioning des couches SIG (ticket #492).

Ce qu'on protège ici : une bascule de millésime ne doit jamais détruire
l'ancien, ne jamais laisser deux millésimes servis en même temps, et
toujours pouvoir revenir en arrière.
"""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from envergo.geodata.models import MAP_TYPES, Map, Zone
from envergo.nitrates.sig_versioning import (
    activer_millesime,
    get_or_create_millesime,
    purger_millesime,
    reactiver_millesime,
)

pytestmark = pytest.mark.django_db

COUCHE = "couche_test"


def _millesime(version, nb_zones=0, actif=False):
    m, _ = get_or_create_millesime(
        name=COUCHE,
        version=version,
        defaults={
            "map_type": MAP_TYPES.zone_action_renforcee,
            "description": "test",
        },
    )
    for i in range(nb_zones):
        Zone.objects.create(
            map=m,
            geometry=(
                "SRID=4326;MULTIPOLYGON((("
                f"{i} 0, {i + 1} 0, {i + 1} 1, {i} 1, {i} 0)))"
            ),
            attributes={"n": i},
        )
    if actif:
        activer_millesime(m)
    return m


def test_millesime_cree_inactif():
    """Un millésime fraîchement créé n'est pas servi : on le remplit
    d'abord, on bascule ensuite. Un import interrompu ne casse rien."""
    m = _millesime("2024")
    assert m.is_active is False
    assert m.version == "2024"


def test_activation_desactive_les_autres():
    a = _millesime("2024", nb_zones=2, actif=True)
    b = _millesime("2026", nb_zones=3)

    activer_millesime(b)

    a.refresh_from_db()
    b.refresh_from_db()
    assert b.is_active is True
    assert a.is_active is False


def test_activation_ne_detruit_pas_les_zones_de_l_ancien():
    """C'est ce qui rend le rollback instantané."""
    a = _millesime("2024", nb_zones=2, actif=True)
    b = _millesime("2026", nb_zones=3)

    activer_millesime(b)

    assert a.zones.count() == 2
    assert b.zones.count() == 3


def test_un_seul_millesime_actif_a_la_fois():
    """Deux millésimes actifs cumuleraient leurs zones : un point
    pourrait matcher l'ancien ET le nouveau zonage."""
    _millesime("2021", nb_zones=1, actif=True)
    _millesime("2024", nb_zones=1, actif=True)
    _millesime("2026", nb_zones=1, actif=True)

    actifs = Map.objects.filter(name=COUCHE, is_active=True)
    assert actifs.count() == 1
    assert actifs.first().version == "2026"


def test_rollback_reactive_un_ancien_millesime():
    _millesime("2024", nb_zones=2, actif=True)
    _millesime("2026", nb_zones=3, actif=True)

    cible = reactiver_millesime(name=COUCHE, version="2024")

    assert cible.version == "2024"
    assert cible.is_active is True
    assert Map.objects.get(name=COUCHE, version="2026").is_active is False


def test_rollback_sur_millesime_inconnu_leve_une_erreur_lisible():
    _millesime("2026", actif=True)
    with pytest.raises(ValueError, match="2019"):
        reactiver_millesime(name=COUCHE, version="2019")


def test_purge_refuse_le_millesime_actif():
    """Garde-fou : purger l'actif laisserait la couche non servie."""
    _millesime("2026", nb_zones=2, actif=True)
    with pytest.raises(ValueError, match="ACTIF"):
        purger_millesime(name=COUCHE, version="2026")


def test_purge_supprime_un_millesime_inactif_et_ses_zones():
    _millesime("2024", nb_zones=2)
    _millesime("2026", nb_zones=3, actif=True)

    _, nb = purger_millesime(name=COUCHE, version="2024")

    assert nb == 2
    assert not Map.objects.filter(name=COUCHE, version="2024").exists()
    assert Map.objects.get(name=COUCHE, version="2026").zones.count() == 3


def test_reimport_du_meme_millesime_est_idempotent():
    a, created1 = get_or_create_millesime(
        name=COUCHE, version="2026", defaults={"description": "x"}
    )
    b, created2 = get_or_create_millesime(
        name=COUCHE, version="2026", defaults={"description": "x"}
    )
    assert created1 is True
    assert created2 is False
    assert a.pk == b.pk


def test_millesimes_differents_coexistent():
    _millesime("2021")
    _millesime("2024")
    _millesime("2026")
    assert Map.objects.filter(name=COUCHE).count() == 3


def test_bascule_repointe_le_critere_vers_le_millesime_actif():
    """Régression (dev, 24/09/2026) : `Criterion.activation_map` pointait
    encore sur le millésime désactivé après bascule. Le critère
    « arbre_decision » ne s'activait donc plus, et TOUS les parcours du
    simulateur renvoyaient « concerné » sans aucune prescription — sans
    erreur ni 500, donc invisible en supervision."""
    from envergo.moulinette.models import Criterion, Regulation

    ancienne = _millesime("2021", nb_zones=1, actif=True)
    regulation = Regulation.objects.create(regulation="nitrates")
    crit = Criterion.objects.create(
        title="arbre_decision",
        regulation=regulation,
        activation_map=ancienne,
        evaluator="envergo.nitrates.regulations.arbre_decision.CriterionEvaluator",
    )

    nouvelle = _millesime("2026", nb_zones=1)
    activer_millesime(nouvelle)

    crit.refresh_from_db()
    assert crit.activation_map_id == nouvelle.pk


def test_rollback_repointe_aussi_le_critere():
    """Le report de référence doit marcher dans les deux sens, sinon un
    rollback laisserait le critère sur la Map devenue inactive."""
    from envergo.moulinette.models import Criterion, Regulation

    ancienne = _millesime("2021", nb_zones=1, actif=True)
    regulation = Regulation.objects.create(regulation="nitrates")
    crit = Criterion.objects.create(
        title="arbre_decision",
        regulation=regulation,
        activation_map=ancienne,
        evaluator="envergo.nitrates.regulations.arbre_decision.CriterionEvaluator",
    )
    nouvelle = _millesime("2026", nb_zones=1)
    activer_millesime(nouvelle)

    reactiver_millesime(name=COUCHE, version="2021")

    crit.refresh_from_db()
    assert crit.activation_map_id == ancienne.pk


def test_adopte_une_couche_sans_millesime_au_lieu_de_la_dupliquer():
    """Les environnements ont déjà une Map sans millésime (créée par la
    migration nitrates 0002 ou un import antérieur au versioning). Le
    premier import doit l'étiqueter, pas en créer une seconde — sinon la
    couche serait servie en double."""
    ancienne = Map.objects.create(
        name=COUCHE,
        map_type=MAP_TYPES.zv_nitrates,
        description="couche pré-versioning",
    )
    assert ancienne.version == ""

    adoptee, created = get_or_create_millesime(
        name=COUCHE, version="2021", defaults={"description": "x"}
    )

    assert created is False
    assert adoptee.pk == ancienne.pk
    assert adoptee.version == "2021"
    assert Map.objects.filter(name=COUCHE).count() == 1


def test_adoption_ne_vaut_que_pour_le_premier_millesime():
    """Une fois la couche étiquetée, un millésime suivant crée bien une
    nouvelle Map (sinon on écraserait l'ancien au lieu de le conserver)."""
    Map.objects.create(
        name=COUCHE, map_type=MAP_TYPES.zv_nitrates, description="pré-versioning"
    )
    get_or_create_millesime(name=COUCHE, version="2021", defaults={"description": "x"})
    _, created = get_or_create_millesime(
        name=COUCHE, version="2026", defaults={"description": "x"}
    )

    assert created is True
    assert Map.objects.filter(name=COUCHE).count() == 2


# ─── Commande de pilotage ──────────────────────────────────────────────────


def test_commande_activer(capsys):
    _millesime("2024", nb_zones=1, actif=True)
    _millesime("2026", nb_zones=2, actif=True)

    call_command("millesimes_sig", "--couche", COUCHE, "--activer", "2024")

    assert Map.objects.get(name=COUCHE, version="2024").is_active is True
    assert "2024" in capsys.readouterr().out


def test_commande_activer_exige_couche():
    with pytest.raises(CommandError, match="--couche"):
        call_command("millesimes_sig", "--activer", "2024")


def test_commande_signale_couche_sans_millesime_actif(capsys):
    """Cas d'un import --no-activate resté en plan : la couche n'est
    servie par personne, il faut que ça se voie."""
    _millesime("2026", nb_zones=1)

    call_command("millesimes_sig", "--couche", COUCHE)

    assert "AUCUN millésime actif" in capsys.readouterr().out
