# Nitrat'Info, simulateur de réglementation nitrates

Nitrat'Info aide un agriculteur (ou son conseiller) situé en zone vulnérable
nitrates à savoir **quand il a le droit d'épandre** un fertilisant azoté sur une
parcelle donnée. L'utilisateur clique sur sa parcelle, répond à quelques
questions (culture, couvert, type de fertilisant...) et obtient le calendrier
des périodes d'interdiction applicables, avec les prescriptions et les textes
de référence.

C'est un **moteur de recherche réglementaire**, pas un outil de conseil : il
restitue ce que disent les programmes d'actions nitrates (national, régionaux,
zones d'action renforcée) pour la situation décrite, sans recommander de
pratique.

- Production : https://nitrates.beta.gouv.fr
- Porté par le ministère de l'Agriculture (MASA) avec beta.gouv.fr
- Infrastructure (OpenTofu, variables d'environnement, secrets) : repo séparé
  [`betagouv/nitrates-iac`](https://github.com/betagouv/nitrates-iac)

## Origine du code : un fork d'Envergo

Le dépôt est un fork d'[Envergo](https://github.com/MTES-MCT/envergo)
(MTES-MCT). On a gardé le socle technique (Django, GeoDjango, DSFR, modèle
`User`, gestion des couches SIG) et on a construit le simulateur dans une app
isolée, `envergo/nitrates/`.

Les apps métier d'Envergo (moulinette aménagement, guichet unique de la haie,
avis réglementaires, pétitions...) sont toujours présentes **mais dormantes** :
le middleware `SetUrlConfBasedOnSite` route toutes les requêtes vers
`config/urls_nitrates.py`, aucune de leurs pages n'est servie. On ne les
supprime pas pour garder un remerge upstream possible.

Toute modification d'un fichier hors de `envergo/nitrates/` faite pour le
simulateur porte le marqueur `REVERT_AT_MERGE_TIME_FOR_UPSTREAM_ENVERGO` (en
commentaire, ou dans le message de commit pour les commits `nitrates(core):`).
Un `grep` sur ce marqueur donne la liste exhaustive des divergences avec
l'upstream.

Le nom du package Python (`envergo`) et certains noms techniques (base
`envergo`, image `envergo_django`) sont restés tels quels : les renommer
casserait les migrations et le remerge pour aucun gain.

## Architecture

### Le simulateur en une phrase

Une **géolocalisation** (parcelle RPG cliquée sur la carte) détermine quels
**arbres de décision** s'appliquent (national, régional, ZAR) ; le **parcours**
de l'arbre avec les réponses du formulaire mène à des **feuilles** qui portent
les périodes d'interdiction et les **codes de prescription** (PC) ; le rendu
compose le calendrier et les textes.

### Où vit quoi

| Chemin | Rôle |
|---|---|
| `envergo/nitrates/yaml_tree/` | Moteur : chargement des arbres (`loader*.py`), parcours (`parcours.py`), conditions et expressions, feuilles, résolution des PC selon la géographie (`prescriptions.py`), validation structurelle (`validator.py`) |
| `envergo/nitrates/regulations/` | Branchement du moteur dans la `Moulinette` héritée d'Envergo |
| `envergo/nitrates/models*.py` | `DecisionTree` (+ révisions, cycle brouillon / actif / archive), référentiels (cultures, fertilisants, notes, codes de prescription, liens), contenus riches, ouverture géographique, retours utilisateurs, couleurs de zones |
| `envergo/nitrates/views.py` | Simulateur public : formulaire, carte, résultat (rechargement GET complet, pas de htmx côté public) |
| `envergo/nitrates/views_admin_*.py`, `yaml_admin/` | Back-office : éditeur YAML des arbres (htmx), validation des branches, matrice des calendriers, ouverture des départements, rapports Nuclei |
| `envergo/nitrates/contenu_rich/` | Pages et blocs éditoriaux (glossaire, pages du pied de page) compilés en HTML DSFR |
| `envergo/nitrates/zonage_*.py`, `bassins.py`, `sig_versioning.py` | Zonages spécifiques (montagne, note 5, zones Est, zones maïs Bretagne), bassins, bascule de millésime des couches SIG |
| `envergo/nitrates/management/commands/` | Imports SIG, seeds, chargement / export des arbres, provisioning, outillage de validation |
| `envergo/nitrates/specs/` | Arbres canoniques (`arbres_actifs/`), grammaire YAML, contenus riches, blocs de PC : sert à monter une base **neuve** |
| `envergo/nitrates/templates/`, `envergo/static/nitrates/` | Gabarits et JS / CSS du simulateur |
| `config/urls_nitrates.py` | Seul urlconf servi |
| `envergo/contrib/middleware.py` | Routage vers nitrates, verrouillage derrière login (`LOCKDOWN_BEHIND_LOGIN`) |
| `envergo/nitrates/auth.py`, `envergo/admin/site.py` | Connexion admin via ProConnect (OIDC), seule voie d'accès en prod |

### Source de vérité des données

- **Arbres, référentiels, contenus PC** : la **base de chaque environnement**
  fait autorité. On les édite dans l'admin. Le déploiement ne les recharge
  jamais (il écraserait les corrections). Les fichiers de `specs/` ne servent
  qu'à initialiser une base vide (CI, e2e, poste local) et comme sauvegarde
  versionnée (`dump_active_trees`, `dump_referentiels`).
- Propager une donnée d'un environnement à l'autre est un geste explicite,
  hors déploiement.
- Un seul arbre actif par couple (scope, région) ; on archive avant d'activer.

### Couches SIG

| Couche | Source | Commande |
|---|---|---|
| Départements | IGN ADMIN EXPRESS | `import_nitrates_departments` (rejouée au post-deploy) |
| Zones vulnérables (ZV) | Sandre | `import_nitrates_zv` (rejouée au post-deploy) |
| Zones d'action renforcée (ZAR) | Archives versionnées dans `envergo/nitrates/sig/` | `import_nitrates_zar` |
| Parcelles (RPG) | IGN / ASP | `import_nitrates_rpg`, `import_rpg_cultures` |

Le détail (volumes, millésimes, options) est dans
[`envergo/nitrates/README.md`](envergo/nitrates/README.md).

## Démarrer en local

Prérequis : Docker, Node 20 (pour les assets et Playwright, même version que la CI).

```bash
git clone https://github.com/betagouv/nitrates.git && cd nitrates
touch .env   # DJANGO_SETTINGS_MODULE=config.settings.local, ENV_NAME=development
docker compose build
docker compose up -d postgres
docker compose run --rm django python manage.py migrate
docker compose run --rm django python manage.py compilemessages   # obligatoire, sinon les URL restent en anglais et des tests échouent
npm ci && npm run build
```

Monter une base exploitable :

```bash
docker compose run --rm django python manage.py seed_referentiels
docker compose run --rm django python manage.py load_arbres_actifs
docker compose run --rm django python manage.py seed_contenus_rich
docker compose run --rm django python manage.py import_nitrates_departments
docker compose run --rm django python manage.py import_nitrates_zv
# RPG : voir envergo/nitrates/README.md (un ou deux départements suffisent)
```

Puis `docker compose up`. Sans identifiants ProConnect, l'admin passe par le
formulaire mot de passe Django (`createsuperuser`), ouvert par défaut en
`config.settings.local` et fermé partout ailleurs. Le domaine servi vient de
`DJANGO_ENVERGO_NITRATES_DOMAIN`, aucune ligne `Site` à créer.

Si PostGIS se plaint de `type "raster" does not exist` :
`docker compose run --rm postgres create_raster`, puis relancer.

### Variables utiles

| Variable | Effet |
|---|---|
| `DJANGO_LOCKDOWN_BEHIND_LOGIN` | Tout le site derrière login (environnements fermés) |
| `DJANGO_NITRATES_ROOT_OUVERT` | Ouvre la racine publique même sous lockdown |
| `DJANGO_NITRATES_FORM_DEBUG_PANELS` | Panneaux de debug du parcours dans le formulaire |
| `PROCONNECT_CLIENT_ID` / `_SECRET` / `_DOMAIN` | Active ProConnect |
| `DJANGO_NITRATES_PROBE_TOKEN` | Monte la sonde `/_probe/` |

Tout nouveau flag se déclare aussi dans `nitrates-iac` (envs dev / staging /
prod), qui est l'endroit où l'on lit la configuration réelle.

## Approche de code

- **Le métier en français** : modèles, fonctions, commentaires et commits sont
  en français, avec le vocabulaire des textes (feuille, branche, culture
  principale, couvert, fertilisant de type I / II / III...).
- **Le moteur est pur** : `yaml_tree/` ne fait pas de rendu et se teste sans
  HTTP. Toute règle nouvelle passe par la grammaire YAML (`specs/grammaire.yaml`)
  et le validateur avant d'arriver dans un arbre.
- **Pas de règle en dur** : une spécificité régionale se modélise dans l'arbre
  régional ou en PC déclinée (`pc12_zar_ge`...), pas avec un `if region == ...`
  dans le code.
- **Public : HTML serveur + JS minimal**. Le formulaire du simulateur se
  soumet en GET complet ; le JS (`envergo/static/nitrates/`) enrichit sans
  remplacer. htmx est réservé à l'admin.
- **DSFR et RGAA** : composants du Système de design de l'État, liens
  d'évitement conservés, navigation clavier sur la carte.
- **Gabarits Django** : `{# ... #}` uniquement sur une ligne ; au-delà,
  `{% comment %}...{% endcomment %}` (un commentaire `{#` multiligne fuit dans
  le HTML rendu).
- **Migrations additives** entre deux releases (pas de `RemoveField` /
  `DeleteModel` sans plan) : le rollback redéploie du code, pas un schéma.
- **Commits** : `nitrates(<périmètre>): <ce qui change>`, avec la référence de
  carte (`refs #550`). Périmètres usuels : `simulateur`, `admin`, `sig`, `data`,
  `pages`, `carte`, `securite`, `core`.

## Tests

### Python

```bash
docker compose run --rm django pytest envergo/nitrates          # suite nitrates
docker compose run --rm django coverage run -m pytest           # suite complète + couverture
docker compose run --rm django coverage report
```

- `envergo/nitrates/tests/conftest.py` seed les référentiels une fois par
  session et fournit `make_active_tree(yaml_text)` pour monter un arbre actif
  depuis du YAML.
- Préférer les tests du moteur sur des arbres YAML minimaux plutôt que sur les
  arbres réels, sauf pour les tests de branches (`test_branche_*`) qui figent le
  comportement d'un arbre canonique.
- Les commandes de management se testent avec `call_command` et des fichiers
  d'entrée minimaux dans `tmp_path`.

### Périmètre de couverture

La configuration est dans `setup.cfg` (`[coverage:*]`). On mesure **tout le
code Python dont le simulateur se sert**, admin et commandes de management
compris : `envergo/nitrates/` en entier, plus chaque fichier du socle importé
par le runtime nitrates (modèle, admin et backend de `users`, modèles
`geodata`, `admin`, middlewares de `contrib` et `middleware`, `decorators`,
helpers de `utils`). Les apps Envergo dormantes sont hors mesure ; la règle et
la liste sont commentées dans `setup.cfg`. Le seuil `fail_under` est bloquant
en CI : une baisse de couverture bloque le déploiement.

Un nouveau fichier Python sous `envergo/nitrates/` est mesuré d'office : il
arrive avec ses tests. Une commande de management « one-shot » aussi : si elle
ne vaut pas un test, elle ne vaut pas d'être gardée dans le dépôt.

Le rapport HTML de chaque run CI est téléchargeable dans l'onglet *Artifacts*
du run (`coverage-html-<sha>`).

### JavaScript

```bash
npm run test-nitrates-js        # node --test sur envergo/static/nitrates/*.test.js
```

### End-to-end (Playwright)

```bash
npm run playwright:install
npm run e2e-nitrates             # config playwright.config.nitrates.ts, specs dans e2e/nitrates/
```

`.github/workflows/e2e.yml` joue la suite sur une base éphémère (montée avec
`seed_referentiels`, `load_arbres_actifs` et `seed_geodata_e2e`) : en gate des
releases, la nuit, ou à la main. Pas sur les PR (trop long). Les specs
`capture_*` sont des outils de captures pour la validation juriste, pas des
tests. `e2e/nitrates/README_root_public.md`
explique la suite qui reproduit la configuration fermée de staging.

## Qualité du code

`pre-commit install` active les hooks de `.pre-commit-config.yaml` : black,
isort, flake8, djLint (gabarits), stylelint + prettier (CSS / SCSS),
detect-secrets (`.secrets.baseline`). La CI rejoue tous les hooks sur tout le
dépôt.

## Intégration et déploiement continus

| Workflow | Déclencheur | Effet |
|---|---|---|
| `ci.yml` | PR et push sur `main` / `develop` | pre-commit, `makemigrations --check`, arbres canoniques valides, fixture référentiels stable, pytest + seuil de couverture |
| `e2e.yml` | gate des releases, nuit, manuel | Suite Playwright nitrates |
| `deploy-dev.yml` | merge sur `main` | Déploie `nitrates-dev` |
| `deploy-staging.yml` | release GitHub marquée *pre-release* | CI + e2e rejouées sur le tag, puis `nitrates-staging` |
| `deploy-prod.yml` | release GitHub normale | Approbation manuelle, backup Postgres, puis `nitrates-prod` (SecNumCloud) |
| `rollback.yml` | manuel | Redéploie un tag antérieur (code seulement) |
| `restart-nightly.yml` | cron | Redémarrage quotidien (swap Scalingo) |

Le post-deploy (`bin/post_deploy.sh`) joue `migrate` et rafraîchit
départements et ZV (désactivables par `SKIP_NITRATES_*_IMPORT`). Il ne touche pas aux arbres ni aux référentiels.
Détails et opérations manuelles : [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Dépendances

Python : [pip-tools](https://github.com/jazzband/pip-tools). On édite un
`requirements/*.in`, puis `cd requirements && ./compile.sh`.

JS : `npm ci`, avec `ignore-scripts=true` (`.npmrc`) : aucun script
d'installation de paquet n'est exécuté.

Dependabot est gelé (cf. `.github/dependabot.yml`) depuis la campagne
d'attaques npm d'août 2026 : chaque montée de version est auditée à la main
(âge de la version, advisories, diff publié vs tag) avant merge.

## Sécurité

- Admin : ProConnect seul en prod (`ADMIN_PASSWORD_LOGIN_DISABLED`), TOTP exigé
  (`DJANGO_ADMIN_OTP_REQUIRED`).
- En-têtes : CSP (`envergo/middleware/csp.py`, `envergo/utils/csp.py`) et
  `envergo/nitrates/middleware.py`.
- Limitation de débit par IP : `envergo/middleware/rate_limiting.py`
  (`RATELIMIT_HARD_RATE`, `RATELIMIT_SOFT_RATE`).
- Scan Nuclei local uniquement : `python manage.py nuclei_scan --target <url>`,
  rapports dans `nuclei_reports/` (jamais commités, refus d'exécution en CI).

## Glossaire

- **ZV** : zone vulnérable aux nitrates, où s'appliquent les programmes d'actions.
- **PAN** : programme d'actions national (arbre `scope=national`).
- **PAR** : programme d'actions régional, qui complète ou renforce le PAN
  (arbre `scope=region`).
- **ZAR** : zone d'action renforcée, sous-zone d'un PAR avec des mesures en plus
  (arbre `scope=zar`).
- **PC** : code de prescription affiché sous le calendrier, décliné selon la
  géographie (`CodePrescription`).
- **RPG** : registre parcellaire graphique, les parcelles déclarées à la PAC.
- **PAC** : politique agricole commune.
- **SIG** : système d'information géographique (ici, les couches importées en
  PostGIS).
- **DSFR** : système de design de l'État.
- **MASA** : ministère de l'Agriculture et de la Souveraineté alimentaire.
- **ProConnect** : fournisseur d'identité des agents de l'État (OIDC).
