# Déploiement — Simulateur nitrates

Ce document couvre **uniquement** le pipeline de déploiement du fork
nitrates (Min. Agriculture / beta.gouv.fr). Pour le code applicatif, voir
le `README.md`. Pour le upstream Envergo, voir
[Recette et déploiement](../README.md#recette-et-déploiement).

## Architecture

| Brique | Outil | Repo / lieu |
|---|---|---|
| Code applicatif | Django + PostGIS | ce repo (`betagouv/nitrates`) |
| Infrastructure | OpenTofu + provider Scalingo | repo séparé `betagouv/nitrates-iac` |
| Hébergement | Scalingo (région `osc-fr1`) | app `nitrates-staging` (prod à venir) |
| Auth admin | ProConnect (OIDC) | env d'intégration ProConnect |

Le code applicatif et l'infrastructure sont **dans deux repos distincts**.
Modifier les variables d'env, le plan Postgres, les secrets, les domaines
custom = `nitrates-iac`. Modifier le code Django = ce repo.

## Flux de déploiement

```
                    ┌─────────────────┐
                    │ ce repo         │
                    │ feature/xxx     │
                    └────────┬────────┘
                             │ merge --ff
                             ▼
                    ┌─────────────────┐         ┌──────────────────┐
                    │ deploy/staging  │────push▶│ scalingo:master  │
                    │ (worktree dédié)│         │ -> build + deploy│
                    └─────────────────┘         └──────────────────┘
                             ▲
                             │ git fetch local
                             │
                    ┌─────────────────┐
                    │ ce repo         │
                    │ origin-betagouv │
                    └─────────────────┘
```

Côté infra, en parallèle :

```
┌──────────────────┐         ┌──────────────────┐
│ nitrates-iac     │─tofu──▶ │ Scalingo API     │
│ envs/staging/    │  apply  │ (env vars,       │
│ main.tf          │         │  addons,         │
│ secrets.enc.yaml │         │  scaling)        │
└──────────────────┘         └──────────────────┘
```

Les deux flux sont **indépendants** :
- Push Scalingo → redéploie le code (build, migrate, restart)
- Tofu apply → ajuste env vars / plan addon (restart automatique de l'app)

Tu peux faire l'un sans l'autre selon ce qui change.

## Setup machine (une seule fois)

Voir [`nitrates-iac/docs/setup-local.md`](https://github.com/betagouv/nitrates-iac/blob/main/docs/setup-local.md)
pour installer les outils (`tofu`, `sops`, `age`, `scalingo` CLI), récupérer
la clé age, et exporter les env vars (`SCALINGO_API_TOKEN`,
`TF_VAR_encryption_passphrase`).

Ce repo lui-même demande juste Docker (cf. README "Démarrage > Avec Docker").

### Worktrees git

Le déploiement se fait depuis un worktree git séparé pour ne pas mélanger
le code en cours de dev avec le code déployé. Convention :

```bash
# Une fois, à la racine du repo (où la .git/ vit) :
git worktree add ../envergo-nitrates-deploy deploy/staging
```

- Worktree dev : tu travailles sur tes feature branches
- Worktree deploy : ne contient que la branche `deploy/staging`, alignée
  sur ce qui doit être push Scalingo. Pas de bidouille en cours dedans.

## Déployer une nouvelle version applicative

### Cas standard : du code en `feature/xxx` à pousser sur staging

```bash
# 1. Aller dans le worktree de deploy
cd ../envergo-nitrates-deploy   # ajuster selon ton arbo

# 2. Récupérer la branche depuis ton clone local de dev
git fetch /chemin/vers/le/worktree/dev feature/xxx
git merge --ff-only FETCH_HEAD

# 3. Push Scalingo (déclenche build, migrate, postdeploy)
git push scalingo deploy/staging:master

# 4. Suivre les logs en direct
scalingo --app nitrates-staging logs --follow
```

Le `Procfile` enchaîne :
1. `postcompile` : `bin/build_assets.sh` (npm build, collectstatic, compilemessages)
2. `web` : démarre gunicorn
3. `postdeploy` : `bin/post_deploy.sh` (migrate, imports SIG)

Build typique : ~10 min (collectstatic 11k fichiers + post-process). À
prévoir avant une démo.

### Cas où ce sont juste des env vars / secrets qui changent

Pas besoin de `git push scalingo`. Modifier `nitrates-iac` puis
`tofu apply` redémarrera l'app avec les nouvelles vars.
Voir [`nitrates-iac/docs/runbook.md`](https://github.com/betagouv/nitrates-iac/blob/main/docs/runbook.md).

### Vérifier le succès

```bash
scalingo --app nitrates-staging deployments | head -3
# La 1ère ligne doit avoir status=success

curl -sI https://nitrates-staging.osc-fr1.scalingo.io/ | head -3
# Doit redirect vers /<admin-url>/login/
```

## Rollback

Voir [`nitrates-iac/docs/runbook.md`](https://github.com/betagouv/nitrates-iac/blob/main/docs/runbook.md)
section "Rollback du code applicatif" et "Rollback de l'infra Tofu".
Résumé :

```bash
scalingo --app nitrates-staging deployments        # récupère le SHA précédent
cd worktree-deploy
git push scalingo <sha>:master --force
```

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

## Limites connues du setup actuel

- **Pas de CI** : `tofu apply` et `git push scalingo` se font à la main
  depuis un poste local. Risque de drift si plusieurs personnes opèrent
  en parallèle.
- **Pas de prod** : seul `staging` est provisionné. Le scaffolding
  `envs/prod/` côté `nitrates-iac` sera ajouté quand le go prod sera
  donné.
- **User Postgres non rotable** : le user système Scalingo ne peut pas
  être changé. Pour la prod, on créera un user `nitrates_app` dédié dès
  le setup initial. Cf. `nitrates-iac/docs/runbook.md`.
