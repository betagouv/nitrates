# Snapshot Miro — types de fertilisant — 2026-04-28

Mapping entre les **libellés fertilisant affichés dans le formulaire
utilisateur** et les **types réglementaires** (Type 0, Ia, Ib, II, III)
qui pilotent la suite de l'arbre de décision.

## /!\ Fiabilité

Export PDF Miro du 2026-04-28. **Non fiable** :
- coquilles d'export visibles dans le texte brut (ex: `ttyyppee IIbI`
  pour "type Ib") ;
- redondances entre catégories (ex: « Composts de fractions solides de
  digestats de méthanisation » apparaît dans Composts ET Digestats) ;
- entrées « directes » ambiguës en bas du board (Type 0, Type Ia,
  Type IB, Type II ou fertilisant inconnu) — fallback ou artefact ?

À recouper avec un juriste avant tout codage du formulaire.

## Contenu

- `types_fertilisant.pdf` — export brut du board Miro
  *« Types de fertilisants -> OK pour dev »*.
- `index.yaml` — extraction structurée :
  - catégories (orange) = 1er niveau de question (fumiers, lisiers,
    composts, digestats, boues, engrais minéral, autre) ;
  - sous-catégories (blanc) = libellé final affiché à l'utilisateur ;
  - type réglementaire (violet) = entrée dans l'arbre de décision —
    NE PAS AFFICHER côté utilisateur.

## Ce qu'il faut en faire côté code

1. Le formulaire pose d'abord la **catégorie** (fumiers/lisiers/...),
   puis affiche les **sous-catégories** correspondantes.
2. Le `type_reglementaire` est **interne** au moteur — il sert à
   indexer la branche `Type 0` / `Ia` / `Ib` / `II` / `III` du
   snapshot `culture_principale/<date>/index.yaml`.
3. Type Ia + Type Ib couvrent visiblement le « Type I » utilisé dans
   l'arbre culture principale 2026-05-08 (sauf pour colza et prairies
   qui parlent de "Type I" tout court). Cohérence à valider avant code.

## Convention de nommage des dossiers

```
snapshot_miro/types_fertilisant/<YYYY-MM-DD>/
  types_fertilisant.pdf
  index.yaml
  README.md
```

`<YYYY-MM-DD>` = date d'export du Miro.
