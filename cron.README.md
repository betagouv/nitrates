# Tâches planifiées (`cron.json`)

REVERT_AT_MERGE_TIME_FOR_UPSTREAM_ENVERGO

Ce fichier documente pourquoi `cron.json` est **vide** dans le fork nitrates.
L'explication vit ici et non dans `cron.json` : le format attendu par le
Scalingo Scheduler ne prévoit que la clé `jobs`, et JSON n'accepte pas de
commentaires.

## Pourquoi les tâches ont été retirées

Le fork ne sert que le simulateur nitrates. Les 5 tâches planifiées héritées
d'Envergo amont opèrent toutes sur des modèles **hors périmètre**
(`Event`, `Request`, `petitions`, `moulinette`) et n'ont aucun effet utile ici.

Elles tournaient chaque nuit et échouaient en silence. En particulier
`obsolete_moulinette_template_admin_alert` (lundi 02:00 UTC, soit 04:00 à
Paris) plantait systématiquement sur `Site.DoesNotExist` :

```python
# envergo/moulinette/management/commands/obsolete_moulinette_template_admin_alert.py:20
current_site = Site.objects.get(domain=settings.ENVERGO_AMENAGEMENT_DOMAIN)
```

`ENVERGO_AMENAGEMENT_DOMAIN` vaut `envergo.beta.gouv.fr` par défaut et n'est
surchargé dans aucun environnement du fork, alors que la base ne porte que
`envergo.local`, `haie.local` et la Site nitrates. Aucun match → crash,
exit code 1.

Le crash n'affectait **que ce one-off nocturne**, jamais une requête web : le
serveur et le simulateur n'ont jamais été impactés. C'était du bruit, pas une
panne — mais du bruit récurrent qui masquait de vraies erreurs dans les logs.

Deux de ces tâches envoyaient de surcroît des **emails à des utilisateurs
Aménagement** (`new_files_user_alert`, `admin_notifications` qui délègue à
`new_files_admin_alert` et `dossier_submission_admin_alert`) : les laisser
tourner sur un environnement nitrates n'était pas souhaitable.

## Ce qu'il faut restaurer au remerge upstream

```json
{
  "jobs": [
    { "command": "42 2 * * * python manage.py populate_log_communes", "size": "M" },
    { "command": "21 */2 * * * python manage.py delete_test_evalreqs", "size": "M" },
    { "command": "10 * * * * python manage.py admin_notifications", "size": "M" },
    { "command": "*/15 * * * * python manage.py new_files_user_alert", "size": "M" },
    { "command": "0 2 * * 1 python manage.py obsolete_moulinette_template_admin_alert", "size": "M" }
  ]
}
```

## Ajouter une tâche planifiée nitrates

Les futures tâches propres à nitrates viennent dans `cron.json`, format :

```json
{
  "jobs": [
    { "command": "0 3 * * * python manage.py ma_commande", "size": "M" }
  ]
}
```

Le Scheduler est activé automatiquement dès qu'un `cron.json` valide est
présent à la racine ; un fichier avec `jobs: []` n'en planifie aucune.
