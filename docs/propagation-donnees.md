# Propager les données métier entre environnements

Les **arbres de décision** et les **référentiels** ne sont pas déployés par la
CI/CD. Ils se propagent à la main, en opération ops délibérée, comme on
traiterait une bascule de données en base.

## Pourquoi à la main

Les données ne suivent pas le cycle de vie du code.

Le **code** descend : dev → staging → prod, par merge, dans ce sens.

Les **arbres** remontent puis redescendent : ils sont édités là où se trouve
la connaissance métier — en pratique sur l'environnement le plus élevé, par
les juristes, via l'éditeur YAML de l'admin — et doivent ensuite être
propagés vers le bas.

Faire porter ces deux flux inverses par le même pipeline rend l'ensemble
ingérable, et surtout expose à une perte : un déploiement de code n'a aucune
raison de réécrire une règle métier saisie en base.

**L'autorité, c'est la base de l'environnement cible.** Le dépôt n'est qu'un
**miroir** (`dump_active_trees`, `dump_referentiels`), utile pour versionner,
relire et faire des diffs — jamais une source qu'on rejoue aveuglément.

### Ce qui a motivé la bascule (2026-08-11)

Le CD de dev rechargeait les arbres à chaque déploiement. Ce jour-là,
`dump_active_trees --check` a correctement signalé que `national.yaml`
divergeait de la base… et `load_arbres_actifs` a quand même empilé une
version par-dessus. Détecter le conflit sans s'arrêter est le pire des
comportements possibles.

Antérieurement (2026-08-03), une propagation automatique avait déjà écrasé
une suppression de plafonds faite le matin même dans l'admin.

## Sens de propagation

```
   [ édition métier ]
   staging (juristes)
          │
          │  dump sur staging  →  commit dans le dépôt  →  load sur dev
          ▼
        dev  ────────────────────────────────────────────►  prod
                        (même procédure, cible différente)
```

Le dépôt sert de véhicule et de trace entre les deux environnements. Il ne
déclenche rien tout seul.

## Procédure

Toutes les commandes passent par le pool de secrets :

```bash
secret join beta   # une fois par session (TouchID)
```

### 1. Sauvegarder la cible AVANT toute écriture

Non négociable. C'est le seul filet.

```bash
secret exec beta -- scalingo --region <region> --app <app-cible> \
  run --detached "python manage.py dump_active_trees --stdout"
```

Pour une bascule d'ampleur, prendre en plus une sauvegarde Postgres complète
depuis le dashboard Scalingo (addon → Backups).

### 2. Capturer l'état de la SOURCE dans le dépôt

Sur l'environnement qui fait autorité (celui où l'édition a eu lieu) :

```bash
secret exec beta -- scalingo --region <region> --app <app-source> \
  run --detached "python manage.py dump_active_trees"
```

Récupérer les fichiers produits, les poser dans `envergo/nitrates/specs/arbres_actifs/`,
puis **relire le diff git avant de committer**. C'est l'étape de contrôle :
un diff inattendu ici est le signal qu'il faut s'arrêter.

### 3. Vérifier l'écart avec la cible

```bash
secret exec beta -- scalingo --region <region> --app <app-cible> \
  run --detached "python manage.py dump_active_trees --check"
```

- **exit 0** : la cible est déjà alignée, il n'y a rien à faire.
- **exit 1** : la cible diverge. Lire ce que dit la commande, fichier par
  fichier, et **comprendre pourquoi** avant de charger quoi que ce soit. Une
  divergence peut vouloir dire que la cible porte une édition récente qu'on
  s'apprête à perdre.

### 4. Charger sur la cible

Seulement après avoir compris l'écart :

```bash
secret exec beta -- scalingo --region <region> --app <app-cible> \
  run --detached "python manage.py load_arbres_actifs --skip-si-identique"

secret exec beta -- scalingo --region <region> --app <app-cible> \
  run --detached "python manage.py seed_referentiels"
```

`load_arbres_actifs` ne fait jamais d'écrasement en place : il crée une
version draft puis l'active, l'ancienne passant en archive. Une propagation
malencontreuse reste donc rattrapable depuis l'historique des versions dans
l'admin.

### 5. Redémarrer et vérifier

Les loaders sont en `@lru_cache` process-local : sans redémarrage, le web
continue de servir l'ancien contenu.

```bash
secret exec beta -- scalingo --region <region> --app <app-cible> restart web
```

Puis vérifier dans l'admin que les arbres actifs sont ceux attendus, et
passer un cas de simulation connu.

## Environnements

| Env | Région | App |
|---|---|---|
| dev | `osc-fr1` | `nitrates-dev` |
| staging | `osc-fr1` | `nitrates-staging` |
| prod | `osc-secnum-fr1` | `nitrates-prod` |

## Ce que fait la CI/CD, et ce qu'elle ne fait pas

**Elle déploie du code** : archive, migrations, imports SIG idempotents,
restart, smoke test.

**Elle ne touche jamais** aux arbres, aux référentiels ni aux feuilles de
validation. Le snapshot pris en début de déploiement dev est en **lecture
seule** : c'est une trace, pas une action.
