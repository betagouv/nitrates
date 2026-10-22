# Tableau de bord ops nitrates

Outil local pour voir, comparer et copier les objets éditables du simulateur
nitrates (arbres de décision, codes de prescription, contenus éditoriaux,
référentiels) entre les quatre environnements : local, dev, staging et prod.

Il ne fait pas partie de l'application Django : il tourne sur le poste de
l'ops, à côté de la stack Docker locale, et ne se déploie nulle part.

## À qui il s'adresse

- **À l'ops et aux devs de l'équipe nitrates** qui doivent savoir où en est
  chaque objet métier d'un environnement à l'autre, et propager une correction
  (par exemple une version de PC validée par les juristes) sans passer par du
  SQL ou des commandes à la main.
- **Pas aux juristes ni aux usagers** : ils éditent dans l'admin de chaque
  environnement. L'outil sert à préparer et vérifier ces revues, et à
  appliquer ce qui y a été décidé.

Pourquoi il existe : la base de chaque environnement fait foi pour les objets
éditables (on les modifie dans l'admin). Sans outil, on ne voyait pas les
écarts, et des propagations à l'aveugle ont déjà écrasé des rédactions
(incident des PC du 09/09/2026).

## Ce qu'il fait

- **Relève** les quatre environnements en quelques secondes, en lecture seule.
- **Compare** chaque objet par empreinte (même contenu octet pour octet, ou
  pas), date chaque version, et signale les incohérences : prod différente de
  staging, environnement aval modifié après l'amont, arbre servant une version
  déjà remplacée ailleurs, YAML brut vide...
- **Montre** la différence : champs qui diffèrent, diff du texte stocké, rendu
  des contenus riches tel que le voit l'usager (deux versions côte à côte), et
  un résumé automatique en langage naturel.
- **Copie** un ou plusieurs objets d'un environnement vers un autre, par
  glisser-déposer, via une file d'attente visible, avec garde-fous.
- **Archive** chaque action (lot exact, logs, état d'avant), pour enquêter et
  revenir en arrière.

## Prérequis sur le poste de l'ops

Rien de secret n'est dans ce dossier. Ce qu'il faut avoir sur la machine :

| Quoi | Pourquoi | Vérifier |
|---|---|---|
| macOS ou Linux, Python 3.9 ou plus | le serveur et la commande (bibliothèque standard seulement) | `python3 --version` |
| La stack Docker locale du dépôt lancée (`docker compose up`) | le relevé, l'écriture locale et le rendu riche tournent dans le conteneur Django local (`envergo_django` par défaut) | `docker ps` |
| Le dépôt monté dans ce conteneur, avec `npm ci` fait | le CSS DSFR (`node_modules/@gouvfr/dsfr`) et `envergo/static/nitrates/calendrier.css` pour le rendu riche | `ls node_modules/@gouvfr/dsfr/dist` |
| Le CLI Scalingo | tunnels vers les bases, one-off d'écriture, déploiements | `scalingo --version` |
| Un accès collaborateur aux apps `nitrates-dev`, `nitrates-staging` (région osc-fr1) et `nitrates-prod` (osc-secnum-fr1) | lecture des bases, écriture dev et staging | `scalingo --region osc-fr1 apps` |
| Une clé SSH déclarée sur le compte Scalingo | `scalingo db-tunnel` passe par SSH (par défaut `~/.ssh/id_rsa`) | `scalingo keys` |
| Un jeton d'API Scalingo dans `SCALINGO_API_TOKEN` | tous les appels Scalingo du serveur | voir ci-dessous |
| `git config user.name` / `user.email` | signer les copies dans le journal admin des environnements | `git config user.name` |
| Facultatif : le CLI `claude` connecté au compte de l'ops | résumés automatiques des différences ; sinon lancer avec `--sans-ia` | `claude --version` |

**Le jeton Scalingo** : le lanceur `nitrates-ops` le demande au coffre de
secrets du poste s'il existe (outil `secret`, pool `beta` : le jeton n'est
injecté que dans le process du serveur). Sans cet outil, exporter un jeton
personnel avant de lancer : `export SCALINGO_API_TOKEN=...` (le créer dans le
tableau de bord Scalingo, ne jamais le commiter ni le coller dans un ticket).

## Réglages du poste

Tout a une valeur par défaut adaptée au `docker-compose.yml` du dépôt. Pour un
poste différent, mettre des `export VAR=valeur` dans
`~/.config/nitrates-ops/env` (lu par le lanceur, hors dépôt).

| Variable | Défaut | Rôle |
|---|---|---|
| `NITRATES_OPS_CONTENEUR` | `envergo_django` | conteneur Django local |
| `NITRATES_OPS_URL_LOCALE` | `http://localhost:8000` | site local, pour les liens directs |
| `NITRATES_OPS_DEPOT_LOCAL` | le dépôt qui contient cet outil | dépôt monté dans le conteneur (git du code local, CSS du rendu) |
| `NITRATES_OPS_AUTEUR` | nom git, puis début de l'e-mail git | comptes Django qui signent les copies, essayés dans l'ordre |
| `NITRATES_OPS_ECRITURE` | local, dev et staging en réel, prod interdite | ex. `staging=simulation` pour jouer sans écrire |
| `NITRATES_OPS_PORT` | `8765` | port du serveur local |
| `NITRATES_OPS_CLE_SSH` | `~/.ssh/id_rsa` | clé SSH pour les tunnels |
| `NITRATES_OPS_CACHE` | `~/.cache/nitrates-ops` | relevés, journal des changements, résumés |
| `NITRATES_OPS_ARCHIVE` | `~/.local/state/nitrates-ops/archive` | archive des actions |

## Lancer

```
tools/ops-dashboard/nitrates-ops                  # serveur http://127.0.0.1:8765, relève les 4 envs, ouvre la page
tools/ops-dashboard/nitrates-ops --envs local     # relevé initial de local seulement
tools/ops-dashboard/nitrates-ops --sans-ia        # sans résumé automatique
tools/ops-dashboard/nitrates-ops --render-only    # page statique en lecture seule, depuis les derniers relevés
```

Ctrl-C arrête le serveur. Après un redémarrage, recharger la page (le jeton
de sécurité change).

## Lire la page

- Une ligne par objet (clé naturelle : identifiant de PC, clé de contenu,
  périmètre et région d'un arbre), une colonne par environnement.
- **Lettre = identité du contenu** : même lettre, même contenu. A est la
  version écrite le plus récemment, B la suivante, etc.
- **Couleur = retard sur la version A** : sarcelle si à jour, puis jaune,
  ambre, et rouge à trois mois et plus. Gris : date inconnue. Hachures : absent.
- **Empreintes** : SHA-256 du JSON canonique des champs stockés. Les id,
  horodatages, auteurs et verrous sont exclus, les clés étrangères sont
  remplacées par la clé naturelle de l'objet visé. Les champs décommissionnés
  des PC (`texte_court`, `texte_redaction_initiale`) sont ignorés.
- **Dates** : `updated_at` quand la table l'a, sinon journal de l'admin, sinon
  historique des contenus (0.6.4 et plus). Une écriture par commande ou SQL ne
  laisse aucune trace. L'entrée « État initial » de l'historique est affichée
  (« existait le... ») mais ne compte pas pour l'ordre. Une copie faite par
  l'outil ne rajeunit pas un contenu : elle note la date d'écriture d'origine.
  La fiche d'un objet explique l'ordre (« Pourquoi cet ordre »).
- **Derniers changements** : ce qui a bougé entre deux relevés d'un même env.
- **Liens directs** : ↗ dans chaque case et boutons dans la fiche (admin de
  l'env, aperçu du contenu riche, vue et édition d'un arbre).

## Agir

- Glisser une case sur une autre colonne de la même ligne, ou cocher des
  cases (ou une colonne entière) puis « copier vers ». Les opérations vont dans
  le **paquet** (dock à droite), « Lancer » crée une tâche par couple
  source et cible.
- **File d'attente** : une tâche à la fois, dans l'ordre d'arrivée, logs en
  direct. Les cases visées clignotent avec la référence de la tâche ; à la fin,
  l'environnement cible est relu.
- Une copie s'exécute **dans l'environnement cible, avec son propre code** :
  `docker exec` en local, one-off `scalingo run --file` ailleurs. Elle passe
  par l'ORM (cycle brouillon, actif, archive des arbres ; signaux de cache ;
  journal admin ; historique des contenus).
- **Supprimer** (propager une absence, par exemple une PC décommissionnée en
  staging) : glisser une case « absent » sur la colonne où l'objet existe
  encore, ou cocher des cases absentes puis « copier ou propager vers », ou
  « ✕ supprimer en … » dans la fiche. Une PC encore citée par un arbre actif
  de l'environnement cible n'est pas supprimée, ni un objet dont la
  suppression en emporterait ou modifierait d'autres (même calcul que l'admin
  Django). Un arbre n'est jamais effacé : l'actif passe en archive. L'état
  d'avant est archivé, la suppression se restaure comme une copie.
- **Garde-fous** : tout ou rien (une transaction par lot), refus si la cible a
  changé depuis l'affichage, vérification après écriture que la cible est
  identique à la source, redémarrage du web Scalingo (caches par process).
  L'écriture vers la prod est interdite.

## Archive et retour arrière

Dans `~/.local/state/nitrates-ops/archive/` (hors cache, à ne pas effacer) :

- `taches/T-xxxx.json` : chaque tâche complète (opérations, logs, résultat).
  Relue au démarrage ; une tâche coupée par un arrêt du serveur apparaît
  « interrompue », il faut alors vérifier la cible.
- `lots/T-xxxx.json` : le lot exact envoyé et l'état de chaque objet cible
  juste avant la copie.
- `actions.jsonl` : une ligne par événement, en ajout seul.

Dans les logs d'une copie appliquée, « Restaurer l'état d'avant » remet le
contenu archivé, par le même moteur. Un objet que la copie avait créé n'est
pas supprimé.

## Sécurité

- Lecture : sessions Postgres en `default_transaction_read_only`, par tunnel
  ouvert le temps du relevé. Le mot de passe de la base passe au conteneur par
  stdin, jamais en ligne de commande.
- Serveur sur `127.0.0.1` seulement ; les écritures exigent un jeton tiré au
  démarrage et un en-tête `Host` local (une autre page du navigateur ne peut
  pas déclencher de copie).
- Le préfixe secret de l'admin de chaque environnement est lu dans ses
  variables Scalingo pour construire les liens ; il reste sur le poste.
- Relevés, archive et page contiennent des données de prod : ils restent sur
  le poste, hors du dépôt.
- Les résumés envoient les diffs de contenu réglementaire au fournisseur du
  modèle de langage, avec le compte de l'ops ; `--sans-ia` pour s'en passer.

## Fichiers

| Fichier | Rôle |
|---|---|
| `nitrates-ops` | lanceur (réglages du poste, jeton Scalingo) |
| `nitrates_ops.py` | commande, tunnels Scalingo, relevés |
| `collect_snapshot.py` | relevé en SQL brut, lecture seule (dans le conteneur local) |
| `render.py` | comparaison, lettres, retards, signaux, diffs |
| `serveur.py` | serveur HTTP local, file d'attente, journal, archive |
| `executeur.py` | lots de copie et de restauration, exécution sur la cible |
| `apply_lot.py` | application dans la base cible (concaténé derrière `collect_snapshot.py`) |
| `rendu.py` | rendu DSFR des contenus riches par le compilateur de l'application |
| `resumes.py` | résumés automatiques des différences (CLI `claude`) |
| `template.html` | la page |
| `test_render.py` | tests |

## Maintenir

- Tests : `python3 -m unittest discover -s tools/ops-dashboard` (sans base ni
  réseau). Ils ne sont pas joués par le pytest de l'application.
- Le relevé n'utilise pas l'ORM : il lit le schéma de chaque base, pour
  tolérer une prod en retard d'une release. Ajouter une famille d'objets :
  une entrée dans `REFERENTIELS` (`collect_snapshot.py`), dans `FAMILLES`
  (`render.py`) et dans `FAMILLES_MODELES` (`apply_lot.py`).
- Changer le calcul des empreintes : incrémenter `SCHEMA` dans
  `collect_snapshot.py`, sinon le journal verrait tous les objets « modifiés ».
- Ajouter un environnement : `ENVS` dans `nitrates_ops.py` (région, app, port
  de tunnel, URL).

## Limites connues

- Pas encore relevés : validation des branches (`BrancheValidation`), couches SIG.
- Après une écriture en local, le site local garde son cache : redémarrer le
  conteneur Django pour voir le changement dans le simulateur.

## Dépannage

| Symptôme | Cause probable |
|---|---|
| « port 1043x déjà occupé » | un ancien tunnel tourne encore : `pgrep -fl db-tunnel` |
| Relevé local en échec | conteneur arrêté ou mal nommé : `NITRATES_OPS_CONTENEUR` |
| Copie refusée, « la cible a changé depuis l'affichage » | relevé périmé (édition ou migration depuis) : relever l'env, puis recommencer |
| Tâche « ok » mais rien n'a changé | l'env cible était en simulation (`NITRATES_OPS_ECRITURE`) |
| Rendu riche sans style | `npm ci` pas fait dans le dépôt de `NITRATES_OPS_DEPOT_LOCAL` |
| « Refusé : jeton ou hôte refusé » | serveur redémarré : recharger la page |
