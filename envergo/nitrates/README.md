# envergo.nitrates

Simulateur nitrates — règlementation épandage pour les agriculteurs en zones
vulnérables (PAN + PAR). Fork Envergo.

## Import du référentiel codes culture RPG

Table de référence des 144 codes culture utilisés par le RPG (PAC). Le CSV
officiel IGN/ASP est embarqué dans `envergo/nitrates/assets/`.

```bash
# Mode insert (défaut, non destructif) : ajoute uniquement les codes manquants
docker compose run --rm django python manage.py import_rpg_cultures

# Mode override : met à jour libellé et groupe pour tous les codes du CSV
docker compose run --rm django python manage.py import_rpg_cultures --mode override

# Avec un autre CSV (ex: nouveau millésime)
docker compose run --rm django python manage.py import_rpg_cultures \
  --file ./assets/REF_CULTURES_2025.csv --mode override
```

À lancer **après** `import_nitrates_rpg` pour que les libellés des cultures
remontent dans la cartouche debug.

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

## Arbre de décision : DB vs fichier YAML

La source de vérité runtime de l'arbre de décision est la table
`nitrates_decisiontree`. Le fichier YAML dans `NITRATES_SPECS_DIR` reste
le format d'import et d'export (backup git).

Au premier `migrate`, l'arbre est **auto-importé** depuis
`NITRATES_SPECS_DIR/arbre_decision_national.yaml` si le fichier est
accessible (cf. migration data `0004_import_initial_decision_tree`). Si
le fichier n'est pas accessible (CI sans bind mount), la migration no-op
silencieusement.

Pour réimporter manuellement après modification du YAML :

```bash
# 1er import (table vide) : crée le tree actif
docker compose run --rm django python manage.py import_decision_tree \
  /specs/arbre_decision_national.yaml --mode auto

# Mise à jour : crée un draft + active immédiatement (l'actif courant
# passe en archive)
docker compose run --rm django python manage.py import_decision_tree \
  /specs/arbre_decision_national.yaml --mode force-active

# Préparer une nouvelle version sans l'activer
docker compose run --rm django python manage.py import_decision_tree \
  /specs/arbre_decision_national.yaml --mode draft --name pan_v2
```

L'arbre est validé (`validate_arbre()`) avant insertion ; en cas de YAML
non conforme, la commande échoue avec la liste des erreurs et n'écrit
rien. Le YAML brut (round-trip ruamel) est conservé sur le tree pour
permettre l'export et la coloration syntaxique dans le viewer admin.
