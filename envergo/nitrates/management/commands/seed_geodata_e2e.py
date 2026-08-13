"""Pose des donnees geo *minimales* pour les tests e2e sur base ephemere.

Pourquoi cette commande existe
------------------------------
Les specs Playwright nitrates simulent un clic sur la carte a des
coordonnees reelles (Reims, Rennes) et attendent un resultat reglementaire.
Ce resultat n'existe que si le point tombe dans une zone vulnerable : sans
couche ZV en base, le simulateur repond « Hors zone » et les ~100 specs
echouent toutes, pour une raison qui n'a rien a voir avec ce qu'elles
testent.

L'import reel (`import_nitrates_zv`) telecharge ~37 Mo depuis le WFS Sandre.
Le brancher sur un nightly le rendrait dependant d'un service externe : une
indisponibilite Sandre ferait passer la CI au rouge sans regression de code.
On seede donc ici des rectangles grossiers autour des points testes : la
couche ZV, et les departements que la vue debug resout geographiquement.

Ce n'est PAS un substitut a la vraie couche : la geometrie est fausse
(des boites), seule l'appartenance des points de test est correcte. Reserve
aux bases jetables. La commande refuse de s'executer si des zones reelles
sont deja presentes, pour ne jamais polluer un environnement importe.
"""

from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.management.base import BaseCommand, CommandError

from envergo.geodata.models import MAP_TYPES, Department, Map, Zone

# Boites (lng_min, lat_min, lng_max, lat_max) larges autour des points que
# les specs utilisent. Larges volontairement : un point de test ajoute a
# proximite ne doit pas silencieusement retomber « hors zone ».
# Le code bassin est porte par l'attribut `CdEuBassin` (ancien schema Sandre,
# cf. bassins.bassin_code_from_attributes) : sans lui, la vue debug affiche un
# bassin inconnu et debug_view.spec.ts echoue sur « OUI ... Seine-Normandie ».
BOITES = {
    # Reims / Marne — bassin Seine-Normandie. Couvre 4.03/49.26 et 3.97/49.05.
    "e2e-reims": ((3.5, 48.8, 4.5, 49.5), "FRH"),
    # Rennes / Ille-et-Vilaine — utilise par debug_view et map_overlays.
    "e2e-rennes": ((-2.0, 47.9, -1.2, 48.4), "FRG"),
}

# Departements de test. La vue debug affiche le departement et la region
# resolus geographiquement (`geodata.Department`) : sans eux, le cartouche
# reste vide et debug_view.spec.ts echoue sur « 51 » / « Grand Est ».
# L'import reel (ADMIN EXPRESS COG, ~250 Mo depuis l'IGN) est hors de portee
# d'un nightly, meme raison que pour la ZV.
DEPARTEMENTS = {
    # Marne — Grand Est. Doit couvrir Reims.
    "51": (3.5, 48.8, 4.5, 49.5),
    # Ille-et-Vilaine — Bretagne. Doit couvrir Rennes.
    "35": (-2.0, 47.9, -1.2, 48.4),
}


class Command(BaseCommand):
    help = "Seede ZV + departements minimaux (rectangles) pour l'e2e sur base jetable."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Seede meme si des zones existent deja (les remplace).",
        )

    def handle(self, *args, **options):
        carte, _ = Map.objects.get_or_create(
            map_type=MAP_TYPES.zv_nitrates,
            defaults={
                "name": "ZV nitrates — national",
                "description": "Couche ZV de test (e2e).",
            },
        )

        existantes = Zone.objects.filter(map=carte)
        # Garde-fou : sur un env qui a deja la vraie couche (des milliers de
        # zones Sandre), ecraser serait destructeur et silencieux.
        deja_seedees = set(
            existantes.values_list("attributes__e2e_seed", flat=True)
        ) <= {True}
        if existantes.exists() and not deja_seedees and not options["force"]:
            raise CommandError(
                f"{existantes.count()} zone(s) deja en base sur la carte ZV et "
                "elles ne viennent pas de ce seed. Refus d'ecraser une couche "
                "importee. Utiliser --force si la base est bien jetable."
            )

        existantes.delete()

        for nom, (bbox, code_bassin) in sorted(BOITES.items()):
            boite = Polygon.from_bbox(bbox)
            boite.srid = 4326
            Zone.objects.create(
                map=carte,
                geometry=MultiPolygon(boite, srid=4326),
                attributes={
                    "e2e_seed": True,
                    "name": nom,
                    "CdEuBassin": code_bassin,
                },
            )
            self.stdout.write(f"  {nom:12s} {code_bassin}  bbox={bbox}")

        for code, bbox in sorted(DEPARTEMENTS.items()):
            boite = Polygon.from_bbox(bbox)
            boite.srid = 4326
            Department.objects.update_or_create(
                department=code,
                defaults={"geometry": MultiPolygon(boite, srid=4326)},
            )
            self.stdout.write(f"  departement {code}  bbox={bbox}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Seed e2e : {len(BOITES)} zone(s) ZV, "
                f"{len(DEPARTEMENTS)} departement(s)."
            )
        )
