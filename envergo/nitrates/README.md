# envergo.nitrates

Simulateur nitrates — règlementation épandage pour les agriculteurs en zones
vulnérables (PAN + PAR). Fork Envergo.

## Import des données SIG MVP

Le MVP tourne avec 3 couches géographiques :

### 1. Départements (ADMIN EXPRESS IGN)

Source : [IGN Géoservices](https://geoservices.ign.fr/adminexpress) (Licence Etalab).

Prérequis au filtre `--departments` de l'import RPG.

```bash
docker compose run --rm django python manage.py import_nitrates_departments \
  --file /chemin/vers/DEPARTEMENT.shp
```

101 entités (métropole + DOM). Import quasi-instantané.

### 2. ZV — Zones Vulnérables nitrates (France métropole)

Source : [Sandre](https://www.sandre.eaufrance.fr/atlas/srv/fre/catalog.search#/metadata/8ddc0f01-6708-4b23-a79a-e9bac3beeee6) (Licence Etalab).

```bash
docker compose run --rm django python manage.py import_nitrates_zv \
  --file /chemin/vers/ZoneVuln_delimitation_FXX.shp
```

8 features (1 par bassin hydrographique), ~56 MB. Import en moins d'une minute.

### 3. RPG — Registre Parcellaire Graphique (parcelles PAC)

Source : [data.gouv.fr / IGN](https://www.data.gouv.fr/datasets/rpg) (Licence Etalab).

**Dev local** : RPG 2.2 millésime 2023 (2.7 GB compressé, 6.8 GB décompressé
GeoPackage). 9.8M parcelles France entière.

**Prod (à venir)** : RPG 3.0 millésime 2024 (16 GB compressé multi-volumes,
~40 GB décompressé). Même structure que 2.2 pour nos besoins.

**Dev local — subset conseillé** : un département Grand Est + un département
hors Grand Est (Bretagne par exemple), suffisant pour développer le MVP.

```bash
# Départements ciblés (rapide, ~50k parcelles par département)
docker compose run --rm django python manage.py import_nitrates_rpg \
  --file /chemin/vers/PARCELLES_GRAPHIQUES.gpkg \
  --departments 51,35 \
  --millesime 2023

# France entière (long, ~10M parcelles, plusieurs heures sur laptop)
docker compose run --rm django python manage.py import_nitrates_rpg \
  --file /chemin/vers/PARCELLES_GRAPHIQUES.gpkg \
  --millesime 2023
```

Commande resumable : en cas d'interruption, relancer reprend là où l'import
s'est arrêté. Batchs de 5000 avec `bulk_create`.
