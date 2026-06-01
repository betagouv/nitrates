# Snapshot Miro — arbre de décision complet — 2026-05-30

Export SVG de l'**intégralité de l'arbre de décision** Nitrate à la date
du 2026-05-30, plus sa **transcription en pseudo-code** (si / alors, une
entrée par feuille).

Plus récent que `../2026-04-28/` : à utiliser de préférence pour situer
un sous-arbre. Pour la branche **culture principale**, c'est toujours
`../../culture_principale/2026-05-08/` (PNG validés juriste) qui fait
foi sur le résultat attendu.

## Contenu

- `arbre_decision_complet.svg` — export SVG brut (vecteur, zoomable).
- `pseudocode.md` — transcription texte de l'arbre, extraite
  automatiquement du SVG (286 nœuds + 432 connecteurs) puis reconstruite
  par position. **Lire l'avertissement de fiabilité en tête du fichier.**

## /!\ Fiabilité

Export Miro brut, **non fiable pour générer du code/test directement**
(cf. `../../README.md` point 2). La transcription :

- est **fiable sur l'inventaire** des feuilles (libellés, périodes,
  codes PC) — texte extrait verbatim ;
- est **à recouper** sur le câblage question→feuille (~25 % des
  connecteurs non rattachés de façon certaine) ;
- a été **recoupée avec succès** contre `culture_principale/2026-05-08/index.yaml`
  pour les 6 branches culture principale (aucune divergence).

## Nouveau dans cet export par rapport au 2026-04-28

Les branches **couvert d'interculture longue / courte** — signalées
« NON snapshottées en feuille fine » dans le README du 2026-04-28 — sont
ici transcrites en feuilles dans `pseudocode.md` (sections B.1 et B.2).
Elles restent **à valider juriste** avant d'en faire un `index.yaml`
contractuel.

## Points ouverts signalés dans la transcription

- câblage dense type II du couvert longue « après 01/01 » (≈30 feuilles)
  à confirmer sur le board ;
- sémantique des **flèches violettes** « go to CINE avant 31/12 » depuis
  la branche courte CINE.
