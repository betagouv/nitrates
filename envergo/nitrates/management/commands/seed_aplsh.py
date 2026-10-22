"""Seed des référentiels APLSH Grand Est et Hauts-de-France (POC).

Transcription des arrêtés GREN (PDF scannés lus page à page, copies dans
~/Data/betagouv/specs/APLSH/) :
  - Grand Est : arrêté n° 2025/612 du 10/12/2025, annexe APLSH
  - Hauts-de-France : arrêté du 22/07/2025, annexe n° 14 (coefficients
    seuls — les teneurs N ne sont pas dans l'annexe 14, la calculette les
    demande à l'utilisateur)

Idempotent : update_or_create sur region_code. Crée aussi les quelques
Fertilisant manquants dans notre nomenclature mais présents dans les
GREN (marqués POC dans la description) — la liste canonique reste unique,
les régions n'y attachent que des valeurs.
"""

from django.core.management.base import BaseCommand

from envergo.nitrates.models_aplsh import ReferentielAPLSH
from envergo.nitrates.models_referentiels import Fertilisant

# Fertilisants présents dans les GREN mais absents de la nomenclature
# actuelle. Type réglementaire = meilleure hypothèse POC (à valider juriste).
FERTILISANTS_POC = [
    {
        "identifiant": "fumier_champignons",
        "libelle_public": "Fumiers et composts de champignons",
        "categorie": "fumiers",
        "type_reglementaire": "type_Ia",
    },
    {
        "identifiant": "boues_step",
        "libelle_public": "Boues de station d'épuration",
        "categorie": "boues",
        "type_reglementaire": "type_II",
    },
]

TABLEAU_GE = """\
# GREN Grand Est — arrêté n° 2025/612 du 10/12/2025, annexe APLSH, tableau 1
# (fertilisants d'élevage courants). N total en kg/t ou m³.
# fertilisant | variante | unite | n_total | p_ete | p_automne
fumier_compact_non_susceptible_ecoulement | Bovins — litières accumulées, logettes paillées | t | 5,4 | 40% | 30%
fumier_mou_susceptible_ecoulement | Bovins — mou, faiblement paillé | t | 4,9 | 50% | 40%
fumier_compact_non_susceptible_ecoulement | Bovins — dépôt au champ (2 mois de stockage min.) | t | 6,1 | 25% | 15%
fumier_compact_non_susceptible_ecoulement | Porcins | t | 7,2 | 45% | 35%
fumier_volaille | | t | 18,9 | 45% | 30%
fumier_compact_non_susceptible_ecoulement | Ovins | t | 6,7 | 20% | 15%
fumier_compact_non_susceptible_ecoulement | Caprins | t | 6,1 | 20% | 15%
fumier_compact_non_susceptible_ecoulement | Équins | t | 8,2 | 20% | 15%
dejection_sans_litiere | Lisier de bovins | m3 | 2,9 | 65% | 60%
dejection_sans_litiere | Lisier de bovins non dilué | m3 | 3,4 | 65% | 60%
effluents_peu_charges_elevage | Eaux blanches et eaux vertes seules | m3 | 0,3 | 65% | 60%
dejection_sans_litiere | Lisier de porcs à l'engrais | m3 | 5,8 | 80% | 75%
dejection_sans_litiere | Lisier de porcs mixte | m3 | 3,5 | 80% | 75%
dejection_sans_litiere | Lisier de porcs naisseur | m3 | 2,2 | 80% | 75%
fientes_volailles | Humides | m3 | 15,0 | 70% | 70%
fientes_volailles | Sèches | t | 30,0 | 50% | 45%
dejection_sans_litiere | Lisier de lapins | m3 | 3,3 | 40% | 35%
compost_effluents_elevage | Fumier de bovins | t | 8,0 | 10% | 10%
compost_effluents_elevage | Fumier de porcins | t | 12,1 | 30% | 30%
compost_fientes_volailles | Avec litière | t | 12,2 | 45% | 35%
compost_effluents_elevage | Fumier d'ovins | t | 11,5 | 10% | 10%
"""

GRILLE_GE = """\
# GREN Grand Est — annexe APLSH, tableau 2 (autres fertilisants, sur analyse
# C/N et Nmin/Ntot). Tranches par bornes max ; borne vide = pas de limite.
# cn_max | nmin_ntot_max | p_ete | p_automne
8 | 20% | 50% | 45%
8 | 40% | 60% | 60%
8 | | 70% | 70%
10 | 20% | 45% | 35%
10 | 40% | 50% | 50%
10 | | 60% | 60%
20 | 20% | 20% | 15%
20 | 40% | 40% | 35%
20 | | 60% | 60%
| 20% | 5% | 0%
| 40% | 20% | 20%
| | 30% | 30%
"""

TABLEAU_HDF = """\
# GREN Hauts-de-France — arrêté du 22/07/2025, annexe n° 14. L'annexe ne
# fournit que les coefficients : n_total vide (demandé à l'utilisateur,
# ou à reprendre des annexes composition du même arrêté).
# fertilisant | variante | unite | n_total | p_ete | p_automne
fumier_compact_non_susceptible_ecoulement | Bovins — pailleux | t | | 5% | 0%
fumier_compact_non_susceptible_ecoulement | Bovins — bien décomposé | t | | 25% | 15%
compost_effluents_elevage | Fumier de bovins | t | | 5% | 5%
dejection_sans_litiere | Lisier de bovins non dilué | m3 | | 55% | 50%
dejection_sans_litiere | Lisier de bovins dilué | m3 | | 55% | 50%
fumier_compact_non_susceptible_ecoulement | Ovins et caprins | t | | 25% | 15%
dejection_sans_litiere | Lisier de porcs (naisseur engraisseur) | m3 | | 70% | 65%
dejection_sans_litiere | Lisier de porcs (engraisseur) | m3 | | 70% | 65%
fientes_volailles | Environ 60 % de MS | t | | 50% | 50%
fumier_volaille | | t | | 50% | 40%
compost_fientes_volailles | | t | | 45% | 35%
fumier_champignons | | t | | 25% | 15%
effluents_peu_charges_elevage | Eaux blanches, vertes et brunes | m3 | | 55% | 50%
fumier_compact_non_susceptible_ecoulement | Porcins | t | | 35% | 30%
fumier_compact_non_susceptible_ecoulement | Chevaux | t | | 5% | 0%
vinasses_betterave | Vinasses de sucrerie | m3 | | 50% | 50%
eaux_residuaires | Eaux résiduaires de féculerie | m3 | | 60% | 60%
eaux_residuaires | Autres eaux d'industries agro-alimentaires | m3 | | 60% | 60%
eaux_residuaires | Soluble de pomme de terre | m3 | | 50% | 50%
boues_step | Boues déshydratées | t | | 40% | 40%
boues_step | Boues liquides (environ 5 % de MS) | m3 | | 45% | 45%
boues_step | Boues digérées séchées thermiquement | t | | 30% | 30%
boues_papeterie | C/N > 25 | t | | 0% | 0%
compost_dechets_verts_matures | Composts de déchets verts | t | | 5% | 5%
compost_biodechets | Composts de boues et déchets verts | t | | 20% | 15%
digestat_brut_methanisation | Voie humide, et fraction liquide de séparation de phase | m3 | | 55% | 50%
digestat_brut_methanisation | Voie sèche, et fraction solide de séparation de phase | t | | 25% | 20%
"""


class Command(BaseCommand):
    help = "Seed des référentiels APLSH Grand Est + Hauts-de-France (POC)."

    def handle(self, *args, **options):
        for spec in FERTILISANTS_POC:
            obj, created = Fertilisant.objects.get_or_create(
                identifiant=spec["identifiant"],
                defaults={
                    **spec,
                    "description": (
                        "Ajouté par seed_aplsh (POC calculette APLSH) : présent "
                        "dans les GREN mais absent de la nomenclature initiale. "
                        "Type réglementaire à valider juriste."
                    ),
                },
            )
            if created:
                self.stdout.write(f"Fertilisant créé : {obj.identifiant}")

        referentiels = [
            {
                "region_code": "44",
                "intitule": "GREN Grand Est — arrêté modificatif APLSH du 10/12/2025",
                "source": (
                    "Arrêté préfectoral n° 2025/612 du 10/12/2025 (DREAL/DRAAF "
                    "Grand Est), annexe « azote potentiellement libéré jusqu'en "
                    "sortie d'hiver (APLSH) »"
                ),
                "fin_apports_ete": "15/09",
                "fin_apports_ete_generique": "30/09",
                "tableau_produits": TABLEAU_GE,
                "tableau_generique": GRILLE_GE,
                "notes": (
                    "Zone climatique semi-continentale pour toute la région. "
                    "Bornes de saison différentes entre tableau élevage "
                    "(15/09-16/09, réf. 15/08 et 15/10) et grille générique "
                    "(30/09-01/10) — telles quelles dans l'arrêté. Mapping "
                    "fumiers/lisiers par variantes sur la nomenclature PAN. "
                    "Le PAR peut fixer un plafond inférieur en ZAR (35 kg à "
                    "confirmer dans le PAR7 GE)."
                ),
            },
            {
                "region_code": "32",
                "intitule": "GREN Hauts-de-France — annexe n° 14 APLSH (22/07/2025)",
                "source": (
                    "Arrêté préfectoral du 22/07/2025 établissant le référentiel "
                    "régional de mise en œuvre de l'équilibre de la fertilisation "
                    "azotée pour la région Hauts-de-France, annexe n° 14"
                ),
                "fin_apports_ete": "31/08",
                "fin_apports_ete_generique": "",
                "tableau_produits": TABLEAU_HDF,
                "tableau_generique": "",
                "notes": (
                    "L'annexe 14 ne fournit que les coefficients (« apports "
                    "d'été (juillet-août) » / « apports d'automne ») : teneurs "
                    "N à saisir par l'utilisateur, ou à reprendre des annexes "
                    "composition de l'arrêté complet. Pas de grille générique : "
                    "produits non listés = références du producteur."
                ),
            },
        ]
        for data in referentiels:
            region = data.pop("region_code")
            obj, created = ReferentielAPLSH.objects.update_or_create(
                region_code=region, defaults=data
            )
            verbe = "créé" if created else "mis à jour"
            self.stdout.write(
                self.style.SUCCESS(
                    f"Référentiel APLSH {region} {verbe} "
                    f"({len(obj.tableau_produits_parse)} produits, "
                    f"{len(obj.tableau_generique_parse)} tranches génériques)"
                )
            )
