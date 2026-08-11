# E2E `root_public_lockdown` — parcours client sous config staging (#202)

Suite de non-régression du **parcours client `/`** dans la configuration qui
n'existe que sur staging : `LOCKDOWN_BEHIND_LOGIN=True` × `NITRATES_ROOT_OUVERT=True`.

## Pourquoi cette suite existe

Incident du 2026-07-02 : le root public était cassé la veille d'un test
utilisateur, et **rien ne l'a détecté**.

Le middleware lockdown (`envergo/contrib/middleware.py`) redirige en **302** vers
`/admin/login/` toute URL non exemptée. Or un `fetch()` navigateur **suit ce 302
en silence** et reçoit la page de login en HTML avec un statut **200** :

- `response.ok === true`
- aucune exception, aucune erreur console
- le blocage se déguise en succès

Symptômes côté client : carte SIG vide, formulaire figé sur « cliquez sur la
carte », au mieux un `Unexpected token 'C', Connexion... is not valid JSON`.

Conséquence pratique : **un smoke « la racine répond 200 » reste vert** pendant
que le site est inutilisable. Un test qui se contente de `expect(response.ok())`
ne voit rien non plus.

D'où la règle de cette suite : sur les endpoints de données, on assert le
**content-type** et le **statut non redirigé** (`maxRedirects: 0`), jamais
seulement `ok`.

## Ce qui est couvert

| Test | Ce qu'il protège |
|---|---|
| `configuration` | Garde-fou : échoue avec un message explicite si le serveur cible n'est pas en config staging (sinon on obtient 4 échecs cryptiques) |
| `donnees : <endpoint>` ×4 | **Le test qui aurait détecté l'incident.** `/geojson/zv/`, `/geojson/zar/`, `/api/referentiels/`, `/simulateur/debug/` → JSON strict, sans redirection |
| `contre-verif` | `/simulateur/` et `/api/arbre/` restent fermés (302). Détecte l'excès inverse : une exemption trop large |
| `page racine` | Carte Leaflet initialisée, couches chargées, zéro erreur console |
| `recherche commune (BAN)` | Saisie → suggestion → recentrage de la carte |
| `parcours complet` | Clic carte → formulaire révélé. Ce wait est à lui seul un test de non-régression : sous l'incident, le formulaire n'apparaissait jamais |

## Lancer en local

La config staging n'existe pas en dev local par défaut — il faut la reproduire.

```bash
# worktree dédié + override compose (lockdown ON + root ouvert, port 8054)
docker compose -p nitrates-e2e202 \
  -f docker-compose.yml -f docker-compose.e2e202.local.yml up -d django node

# la suite tourne DANS le container node (cf. gotcha ci-dessous)
docker exec -e IN_DOCKER=1 nitrates_node_e2e202 \
  npx playwright test --config playwright.config.nitrates.ts \
  root_public_lockdown --reporter=line
```

Attendu : **9 passed**.

## Gate de déploiement

Cette suite est une **gate bloquante** du déploiement staging (étape 9 du skill
ops `nitrates-deploy-staging`). Si elle échoue : rollback, et le déploiement
n'est pas déclaré OK.

## Gotchas rencontrés

1. **Lancer depuis l'hôte charge la mauvaise version de Playwright.** Les
   `node_modules` du worktree sont vides (volume Docker), donc `npx` remonte au
   `~/node_modules` global qui a une autre version → *"Playwright Test did not
   expect test.describe.configure() to be called here"*. **Toujours lancer dans
   le container node.**

2. **`--host-resolver-rules` ne s'applique pas à `request`.** La config nitrates
   fait pointer le *navigateur* sur `127.0.0.1:8000` et corrige l'IP via cette
   option Chromium. Mais `APIRequestContext` est un client HTTP Node, pas le
   navigateur : il tombe sur `ECONNREFUSED`. La spec résout donc l'hôte
   elle-même (`API_BASE` / `API_HEADERS`) tout en gardant le `Host` attendu par
   le middleware Site Django (id=3, `127.0.0.1`).

3. **Les navigateurs ne sont pas préinstallés** dans le container node :
   `npx playwright install chromium` puis, en root,
   `npx playwright install-deps chromium`.

## Validation par sabotage

Un test vert qui ne casse jamais ne protège de rien. La suite a été validée en
reproduisant l'incident : exemption `/geojson/` + `/api/referentiels/` retirée du
middleware → le test `donnees : /geojson/zv/` **échoue** comme attendu.
Middleware restauré ensuite (diff vide).
