# Snapshot Miro — arbre de décision complet — 2026-04-28

Vue d'ensemble de l'**intégralité de l'arbre de décision** Nitrate à
la date du 2026-04-28 (toutes branches : culture principale, couvert
d'interculture, sol non cultivé, types de fertilisant et leurs notes).

## Pourquoi ce dossier existe

- garder une **photo historique** du board avant d'attaquer les
  branches non encore modélisées (couverts d'interculture, sol non
  cultivé) ;
- repérer rapidement ce qui n'a **pas encore été snapshotté en feuille
  fine** dans les autres dossiers (`culture_principale/`,
  `cultures_formulaire/`, `types_fertilisant/`) ;
- avoir une référence pour situer un sous-arbre dans le contexte
  global métier.

## /!\ Fiabilité

C'est un export Miro brut, **non fiable** pour générer du code ou des
tests directement :
- la mise en forme se déforme à l'export ;
- des notes de travail juridique (« à compléter avec PAR », « deux
  propositions à discuter », commentaires post-it) cohabitent avec les
  règles validées ;
- les règles ont pu évoluer entre le 2026-04-28 et aujourd'hui — le
  snapshot `culture_principale/2026-05-08/` est plus récent et fait
  foi pour cette branche.

## Contenu

- `arbre_decision_complet.pdf` — export PDF (1 page, vue compacte).
- `arbre_decision_complet.svg` — export SVG (vecteur, zoomable —
  format recommandé pour la lecture détaillée).

Pas de `index.yaml` dans ce dossier : les feuilles validées sont
extraites au fur et à mesure dans les dossiers branche par branche
(`culture_principale/`, etc.).

## Branches identifiables sur la vue complète

D'après l'analyse du PDF du 2026-04-28 :

- **Culture principale** :
  - Colza (snapshotté en feuille → `../../culture_principale/2026-05-08/colza.png`)
  - Culture d'hiver autre que colza (snapshotté)
  - Culture de printemps (snapshotté)
  - Prairies implantées >6 mois (snapshotté)
  - Luzerne (snapshotté en 3 captures)
  - Autres cultures (snapshotté)
- **Couvert d'interculture longue** — NON snapshotté en feuille fine.
- **Couvert d'interculture courte** — NON snapshotté en feuille fine.
- **Sol non cultivé** — règle triviale (interdit toute l'année), pas
  besoin de snapshot dédié.

## Convention de nommage

```
snapshot_miro/arbre_complet/<YYYY-MM-DD>/
  arbre_decision_complet.pdf
  arbre_decision_complet.svg
  README.md
```

`<YYYY-MM-DD>` = date inscrite sur l'export Miro (pas la date d'import
dans le repo).
