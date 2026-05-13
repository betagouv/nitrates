# Snapshot Miro — culture principale — 2026-05-08

Capture intégrale de la branche **"culture principale"** du board Miro
juriste, à la date du 2026-05-08.

## Pourquoi ce dossier

Le board Miro est la source métier vivante (les juristes y peignent les
règles avant de les coder en YAML). Ce dossier fige des **points de
référence horodatés** qui servent à :

- comparer ce que rend l'application aux règles peintes ;
- détecter les régressions quand les juristes modifient le board ;
- donner à un agent ou un testeur un contrat clair :
  *« étant donné cette feuille, l'application doit retourner ce
  résultat »*.

## Contenu

- `index.yaml` — tableau exhaustif (une ligne = une feuille de l'arbre)
  avec, pour chaque feuille : culture, type de fertilisant, conditions
  intermédiaires (questions Q1/Q2/Q3/Q4, Notes 5/6/7/12), zonage,
  résultat textuel attendu, code PC final.
- `*.png` — captures originales du board, une par branche culture
  principale. Le YAML pointe vers le PNG dans le champ `screenshot` (ou
  `screenshots_complementaires` pour les branches trop larges qui
  tiennent sur plusieurs captures).

## Ce qui n'est PAS dans ce snapshot

La branche "culture principale" est l'un des sous-arbres de l'arbre
métier. Sont **hors périmètre** ici :

- la résolution amont *« ECG concernée par zone nitrate »* ;
- la branche *« sol non cultivé »* / *« sol non couvert »* ;
- la branche *« sol végétal »*.

Si tu peintures un autre sous-arbre, crée un dossier frère :
`snapshot_miro/<sous_arbre>/<YYYY-MM-DD>/`.

## Convention de nommage

```
snapshot_miro/
  culture_principale/
    2026-05-08/                   # date du snapshot (YYYY-MM-DD)
      index.yaml                  # source unique du tableau récap
      README.md                   # ce fichier
      colza.png                   # une branche = un PNG
      culture_hiver_autre_que_colza.png
      culture_de_printemps.png
      prairies_implantees_plus_de_6_mois.png
      luzerne_partie1.png         # branche large : N captures
      luzerne_partie2.png
      luzerne_partie3.png
      autres_cultures.png
```

Slug = libellé de la branche en `snake_case`, sans accent. Si la branche
ne tient pas en une capture, suffixer `_partieN` et lister les parties
sous `screenshots_complementaires` dans le YAML.

## Ajouter un nouveau snapshot

1. Créer `snapshot_miro/culture_principale/<YYYY-MM-DD>/`.
2. Y déposer les PNG renommés selon la convention.
3. Copier `index.yaml` du snapshot précédent et mettre à jour les
   feuilles modifiées.
4. Dans le commit, signaler explicitement les diffs métier (nouvelle
   feuille, période modifiée, code PC déplacé).

## Lecture rapide du YAML

```yaml
- branche: colza
  screenshot: colza.png
  feuilles:
    - type_fertilisant: "Type III"
      condition: null
      zonage: "Note 5"
      resultat: "Autorisé sous condition du 01/09 au 15/10 et Interdit du 15/10 au 15/01"
      code_pc: "PC11"
```

Se lit : *« sur la branche colza, pour un fertilisant Type III en zonage
Note 5 (PACA, Occitanie, Dordogne, Gironde, Landes, Lot-et-Garonne,
Pyrénées-Atlantiques), l'application doit retourner la règle PC11
"colza" avec la fenêtre 01/09–15/10 autorisée sous condition et 15/10–
15/01 interdite. »*

Les codes PC, types de fertilisant et notes (zonages réglementaires)
sont récapitulés en tête de `index.yaml`.
