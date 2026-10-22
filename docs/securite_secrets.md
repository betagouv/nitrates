# Détection de secrets dans le code

Ce document décrit comment on empêche les secrets (mots de passe, jetons
d'accès, clés privées) de fuiter dans le dépôt, et quoi faire quand l'outil
se déclenche.

## Les trois lignes de défense

1. **En local, au commit** : le hook pre-commit `detect-secrets` (Yelp)
   scanne les fichiers stagés et bloque le commit si une chaîne suspecte
   n'est pas déjà répertoriée dans `.secrets.baseline`.
2. **En CI** : le workflow `ci.yml` rejoue tous les hooks pre-commit sur
   l'ensemble des fichiers (`pre-commit/action`). Un commit poussé avec
   `git commit --no-verify` est donc rattrapé : la CI échoue.
3. **Côté GitHub** : le *secret scanning* et la *push protection* sont
   activés sur `betagouv/nitrates` (dépôt public). GitHub refuse un push
   contenant un jeton reconnu (tokens GitHub, AWS, etc.) et alerte sur
   l'historique. État au 2026-09-10 : zéro alerte.

## Installer le hook en local (obligatoire)

```bash
pip install pre-commit   # ou brew install pre-commit
pre-commit install
```

Sans cette étape, le fichier `.pre-commit-config.yaml` n'est qu'une
déclaration : rien ne tourne au commit. Vérifier avec :

```bash
pre-commit run detect-secrets --all-files
```

## Ce que vérifie detect-secrets

Détecteurs actifs (cf. `plugins_used` dans `.secrets.baseline`) : clés AWS,
Azure, GitHub, GitLab, Stripe, Twilio, etc., mots de passe en clair
(`password = "..."`), identifiants dans des URLs (`user:pass@host`), clés
privées PEM, et chaînes à forte entropie (base64 et hexadécimal).

Le fichier `.secrets.baseline` est la liste des détections **connues et
assumées** (faux positifs : mots de passe factices de tests, identifiants
`envergo:envergo` de la CI, alphabets base64 utilisés comme constantes...).
Tout ce qui n'y figure pas bloque le commit.

## Quand le hook se déclenche

1. **C'est un vrai secret** : le retirer du code (variable d'environnement,
   configuration Scalingo, pool SOPS). Si le commit a déjà été poussé,
   considérer le secret comme compromis : le révoquer et le faire tourner,
   puis prévenir l'équipe. Réécrire l'historique ne suffit jamais.
2. **C'est un faux positif** (valeur factice de test, exemple de doc) :
   mettre à jour la baseline puis la commiter avec le changement :

   ```bash
   detect-secrets scan --baseline .secrets.baseline
   git add .secrets.baseline
   ```

   Le diff de la baseline doit être relu en revue comme du code : une
   nouvelle entrée est une déclaration « ceci n'est pas un secret ».
3. **Inline, au cas par cas** : on peut aussi marquer une ligne avec le
   commentaire `# pragma: allowlist secret` plutôt que de l'ajouter à la
   baseline (préférable pour un fichier de test isolé).

## Entretien de la baseline

Re-générer périodiquement (les numéros de ligne dérivent avec le code) :

```bash
detect-secrets scan --baseline .secrets.baseline
```

Pour re-passer en revue les entrées existantes :

```bash
detect-secrets audit .secrets.baseline
```

## Balayage de l'historique

Le hook ne protège que les nouveaux commits. Pour contrôler l'historique
complet (8600+ commits) :

```bash
brew install gitleaks
gitleaks git --redact .
```

Audit du 2026-09-10 : 30 détections, toutes triées, aucun vrai secret.
Détail : hashes SHA-1 internes de `.secrets.baseline` elle-même,
identifiants factices dans les tests `petitions`, mots de passe Postgres
des environnements Docker locaux (`envs/postgres`), clé de session
aléatoire non sensible d'une commande d'admin. Le secret scanning GitHub
ne remonte rien non plus.

## Pourquoi detect-secrets et pas Talisman

Talisman (ThoughtWorks) a été évalué en complément (carte #442). Verdict :
on garde detect-secrets seul.

- La couverture est équivalente sur notre base : les deux reposent sur des
  motifs + entropie ; les vrais différenciateurs de Talisman (détection
  par nom de fichier suspect, scan d'historique intégré) sont couverts
  respectivement par la baseline et par gitleaks/le secret scanning GitHub.
- detect-secrets est déjà câblé dans pre-commit ET rejoué en CI ; Talisman
  s'installe comme hook git natif hors pre-commit, ce qui complique
  l'installation et ne tourne pas en CI sans travail supplémentaire.
- Deux outils = deux mécanismes d'allowlist à maintenir (`.talismanrc` +
  `.secrets.baseline`) pour les mêmes faux positifs.
