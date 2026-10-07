# Déploiement, simulateur nitrates

Ce document couvre le déploiement de Nitrat'Info sur Scalingo. Pour le code
applicatif, voir le [`README.md`](../README.md).

## Architecture

| Brique | Outil | Lieu |
|---|---|---|
| Code applicatif | Django + PostGIS | ce repo (`betagouv/nitrates`) |
| Infrastructure | OpenTofu + provider Scalingo | repo `betagouv/nitrates-iac` |
| Hébergement dev / staging | Scalingo `osc-fr1` | apps `nitrates-dev`, `nitrates-staging` |
| Hébergement prod | Scalingo SecNumCloud `osc-secnum-fr1` | app `nitrates-prod` (nitrates.beta.gouv.fr) |
| Auth admin | ProConnect (OIDC) | |

Modifier les variables d'environnement, les addons, les secrets ou les
domaines se fait dans `nitrates-iac` (`tofu apply` redémarre l'app). Modifier
le code se fait ici. Les deux flux sont indépendants.

## Flux nominal : GitHub Actions

| Cible | Déclencheur | Workflow |
|---|---|---|
| `nitrates-dev` | merge sur `main` | `deploy-dev.yml` |
| `nitrates-staging` | publication d'une release GitHub marquée *pre-release* | `deploy-staging.yml` |
| `nitrates-prod` | publication d'une release GitHub normale, puis approbation manuelle | `deploy-prod.yml` |

Staging et prod rejouent la CI complète (linter, pytest, seuil de couverture)
et la suite e2e sur le SHA du tag avant d'écrire quoi que ce soit. La prod
déclenche en plus un backup Postgres. Le code part par `git archive` +
`scalingo deploy` (token API dans l'environment GitHub, pas de clé SSH).

Le `Procfile` enchaîne ensuite :

1. `postcompile` : `bin/build_assets.sh` (npm build, collectstatic, compilemessages)
2. `web` : gunicorn
3. `postdeploy` : `bin/post_deploy.sh` (`migrate`, imports départements et ZV)

Le déploiement **ne recharge jamais** les arbres, référentiels ni contenus :
la base de chaque environnement fait autorité. Propager une donnée d'un
environnement à l'autre est un geste explicite.

Entre deux releases, les migrations restent **additives** : le rollback
redéploie du code, pas un schéma.

### Vérifier le succès

```bash
scalingo --app nitrates-staging deployments | head -3   # 1re ligne : status=success
```

## Rollback

Onglet Actions, workflow **Rollback**, choisir l'environnement et le tag à
restaurer. Il redéploie l'archive d'un tag antérieur par le même chemin que le
déploiement nominal (sans gate e2e). Il restaure le code, pas le schéma : en
cas de migration destructive, passer par la restauration du backup Postgres
(cf. `nitrates-iac/docs/runbook.md`).

## Authentification admin (ProConnect)

L'admin Django est protégé par ProConnect (OIDC). **Aucune création de
compte spontanée** : un email ProConnect inconnu en DB est rejeté.

### Provisionner un nouvel admin

```bash
# Via une commande déclenchée sur Scalingo (TTY contournée par fichier) :
cat > /tmp/provision.sh << 'EOF'
#!/bin/bash
python manage.py provision_admin \
  --email prenom.nom@beta.gouv.fr \
  --name "Prénom Nom" \
  --superuser   # ou retirer cette ligne pour un admin non-super
EOF
chmod +x /tmp/provision.sh

scalingo --app nitrates-staging run \
  --file /tmp/provision.sh \
  -- bash /tmp/uploads/provision.sh
```

La commande est idempotente. `--revoke` retire `is_staff` / `is_superuser`
sans supprimer le compte.

Le User créé peut se connecter immédiatement via le bouton
"Se connecter avec ProConnect" sur la page de login admin. À la première
connexion, son `proconnect_sub` (identifiant ProConnect stable) est
persisté et sert de clé de réconciliation primaire pour les connexions
suivantes (l'email reste un fallback).

### Désactiver ProConnect en local

ProConnect est désactivé par défaut en dev local (pas de
`PROCONNECT_CLIENT_ID` chargé). La page login admin retombe sur le form
user/password Django classique.

Pour forcer la désactivation **même** quand les credentials staging sont
chargés par accident :

```bash
export DJANGO_PROCONNECT_DISABLED=True
```

## Imports de données (SIG)

### Départements (auto au déploiement)

Téléchargés depuis IGN (ADMIN EXPRESS COG, ~250 Mo) à chaque
postdeploy. Pour skipper si IGN est down :

```bash
scalingo --app nitrates-staging env-set SKIP_NITRATES_DEPARTMENTS_IMPORT=1
scalingo --app nitrates-staging restart
```

### Zones Vulnérables (manuel)

Sandre étant instable, l'import auto est **off** par défaut sur staging
(`SKIP_NITRATES_ZV_IMPORT=1`). Procédure d'import manuel à partir d'un
shapefile local : voir
[`nitrates-iac/docs/runbook.md`](https://github.com/betagouv/nitrates-iac/blob/main/docs/runbook.md)
section "ZV nitrates (manuel staging)".

L'import est idempotent (clé naturelle Sandre `inspireid` puis
`CdEuZoneVu`). Rejouer N fois = même résultat qu'1 fois.

## Debug express

```bash
# Logs en direct, filtrés
scalingo --app nitrates-staging logs --follow | grep -iE "error|traceback|status=5"

# Shell Django
scalingo --app nitrates-staging run python manage.py shell

# Vérifier qu'une env var est bien set (sans afficher la valeur)
scalingo --app nitrates-staging env | grep -E '^(PROCONNECT|DJANGO_ADMIN)' | sed 's/=.*/=<set>/'

# Vérifier le SHA déployé
scalingo --app nitrates-staging deployments | head -3
```

Pour les pannes plus complexes (DB en recovery, env var manquante au
boot), voir [`nitrates-iac/docs/runbook.md`](https://github.com/betagouv/nitrates-iac/blob/main/docs/runbook.md)
section "Debug".

## Limites connues

- **User Postgres non rotable** : le user système Scalingo ne peut pas être
  changé. Pour la prod, un user applicatif dédié est créé dès le setup
  initial. Cf. `nitrates-iac/docs/runbook.md`.
