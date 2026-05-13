# Snapshot Miro — cultures formulaire — 2026-05-08

Mapping entre les **libellés culture/couvert affichés dans le formulaire
utilisateur** et les **branches de l'arbre de décision** correspondantes.

## /!\ Fiabilité

Ce snapshot vient d'un export SVG Miro du 2026-05-08. Les exports Miro
sont **non fiables** : casse, espaces fins, ponctuation, ordre des
items varient à chaque export. Le YAML signale les divergences connues
avec les snapshots culture_principale validés.

**La source de vérité pour le résultat attendu** reste le PNG snapshot
horodaté de la branche concernée (`../culture_principale/<date>/<branche>.png`).

## Contenu

- `cultures_formulaire.svg` — export brut du board Miro
  *« Types de cultures/couverts -> Ok pour dev »*.
- `index.yaml` — extraction structurée :
  - catégories (orange) = 1er niveau de question dans le formulaire ;
  - sous-catégories (blanc) = libellé final affiché à l'utilisateur ;
  - branche d'arbre (violet) = routage interne — ne pas afficher.

## Ce qu'il faut en faire côté code

1. Côté **formulaire** : afficher les libellés `libelle_formulaire`
   regroupés par `categorie`. Les utiliser tels quels (à reformater
   typographiquement uniquement si nécessaire).
2. Côté **moteur de décision** : à partir du couple `{categorie,
   libelle_formulaire}` choisi, router vers `branche_arbre` puis
   appliquer la règle issue du snapshot
   `../culture_principale/<date>/index.yaml`.
3. Le champ `screenshot_reference` pointe directement vers le PNG
   contractuel — pratique pour générer des fixtures de test.

## Convention de nommage des dossiers

```
snapshot_miro/cultures_formulaire/<YYYY-MM-DD>/
  cultures_formulaire.svg
  index.yaml
  README.md
```

`<YYYY-MM-DD>` = date d'export du Miro.
