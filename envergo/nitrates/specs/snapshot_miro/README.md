# Snapshots Miro — spécifications métier

Photos horodatées du board Miro juriste, qui sert de **source métier
vivante** pour la réglementation Nitrate. Les juristes peignent les
règles dans Miro avant qu'elles soient codées en YAML et exposées aux
utilisateurs.

## Organisation

```
snapshot_miro/
  culture_principale/     # branches culture principale, par date
    2026-05-08/           # PNG + index.yaml exhaustif (feuilles testables)
  cultures_formulaire/    # mapping libellé form → branche d'arbre
    2026-05-08/           # SVG + index.yaml
  types_fertilisant/      # mapping libellé fertilisant → type réglementaire
    2026-04-28/           # PDF + index.yaml
  arbre_complet/          # vue d'ensemble historique (référence, pas de YAML)
    2026-04-28/           # PDF + SVG
```

Chaque sous-dossier daté contient son propre README qui explique
quoi en faire.

## Hiérarchie de fiabilité

1. **Snapshot PNG d'une branche culture principale** validé avec le
   juriste = source de vérité pour le **résultat attendu** que doit
   produire l'application sur cette branche. C'est le contrat de
   test.
2. **Export Miro (SVG / PDF)** = utile pour l'**inventaire** (libellés
   à afficher, mapping vers branches) mais **non fiable** sur la
   forme : casse, accents, ponctuation, ordre se déforment à chaque
   export. À recouper avec le snapshot PNG ou avec le juriste.
3. **YAML des specs codées** (`envergo/nitrates/specs/...` hors
   `snapshot_miro/`) = ce qui tourne réellement en prod. Si le YAML
   diverge d'un snapshot validé, c'est un bug à corriger.

## Ajouter un nouveau snapshot

1. Choisir le sous-dossier qui correspond
   (`culture_principale/`, `cultures_formulaire/`, etc.) ou en créer
   un nouveau au même niveau si c'est un nouveau type de spec.
2. Créer un dossier daté `<YYYY-MM-DD>/` (date d'export Miro, pas
   d'import dans le repo).
3. Y déposer les fichiers source renommés selon la convention du
   sous-dossier.
4. Écrire / mettre à jour `index.yaml` (sauf pour `arbre_complet/` qui
   est une vue de référence).
5. Mettre à jour le README local si nécessaire.

## Hors-scope actuel

- **Notes de bas de page** (notes 1–13 mentionnées dans l'arbre :
  contenu textuel à afficher avec les périodes d'autorisation
  conditionnelle). Encore en construction côté juriste — à snapshotter
  quand stabilisé.
- **Branches couvert d'interculture longue / courte** et **sol non
  cultivé** : visibles dans `arbre_complet/`, pas encore snapshottées
  en feuilles fines.
- **PAR** (programme d'action régional) : pas encore intégré au board.
