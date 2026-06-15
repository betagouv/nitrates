# Rapprochement feuilles couvert ⇄ widgets Miro — rapport

**Date :** 2026-06-15
**But :** associer chacune des 113 feuilles-résultat « couvert d'interculture »
du YAML actif à l'`id` du widget Miro qui affiche son résultat, pour produire
des deeplinks `?moveToWidget=<id>` cliquables (en remplacement des
screenshots).

**Artefacts :**

- `widgets.json` — 1057 widgets du board (id, x, y, w, h, scale, texte).
- `couvert_leaves.json` — 113 feuilles couvert exportées du YAML actif
  (régénérable via `dump_leaves.sh`).
- `mapping_couvert.json` — le rapprochement produit (1 objet par feuille).
- `build_mapping_couvert.py` — script réexécutable qui régénère le mapping.
- `../2026-05-30/couvert_reference_svg.json` — ancien rapprochement (board
  d'une version **antérieure**, phrasé différent) utilisé comme indice seul.

## Méthode

Le board **n'est pas une cascade colonne-par-colonne** exploitable
mécaniquement : une même branche YAML (sous_culture → type fertilisant →
plan d'épandage → IAA/note 5/effluent) aboutit à **plusieurs widgets-résultat**
de **texte identique** mais positionnés différemment (sous-conditions ICPE,
IAA Q6, note 5, effluents peu chargés). Un même libellé « Autorisé sous
condition entre le 15/11 et le 15/01 » apparaît jusqu'à **10 fois** dans une
seule bande.

Le rapprochement se fait donc par **signature** plutôt que par position pure :

1. **Bande (y)** déduite de la sous_culture :
   - `apres_0101` : 5900 ≤ y < 12200 (CINE détruit / CIE exporté après 01/01) ;
   - `avant_3112` : 12200 ≤ y < 16900 (CINE détruit / CIE récolté avant 31/12) ;
   - `courte`     : y ≥ 16900 (couvert d'interculture courte).
   (y < 5900 = culture principale, ignoré.)
2. **Signature date+régime** : la paire de dates fixes JJ/MM de la période
   *headline* (1re période non masquée) du YAML, recherchée dans le texte du
   widget, + l'amorce « Interdit du… » / « Autorisé sous condition… ».
3. **CIE vs CINE** : filtre par présence/absence de la clause d'implantation
   (« 15 jours avant l'implantation », « Pas d'apport avant ») — discriminant
   typique CINE.
4. **Désambiguïsation finale** par recoupement avec l'ancien `svg_proche`
   et cohérence de voisinage.

La bande courte (4 feuilles × CIE/CINE) est mappée **en dur** : zone petite,
fixe, vérifiée widget par widget (le code PC tranche : PC13 = CINE, PC15 = CIE).

## Compteurs

| confiance | n   | sens                                                            |
|-----------|-----|-----------------------------------------------------------------|
| **haute** | 13  | texte unique dans la bande (ou bande courte vérifiée à la main) |
| **moyenne**| 68 | résultat (période + régime) **sûr**, mais l'instance de widget exacte parmi les doublons ICPE/IAA/note5 reste à confirmer visuellement |
| **basse** | 32  | pas de match fiable (voir détail ci-dessous) → `miro_widget_id` renseigné en best-effort ou vide |
| **TOTAL** | 113 |                                                                 |

3 feuilles ont `miro_widget_id = ""` (aucun widget proposé).

### Répartition par sous_culture

| sous_culture     | haute | moyenne | basse |
|------------------|-------|---------|-------|
| cie_apres_0101   | 2     | 27      | 2     |
| cine_apres_0101  | 2     | 27      | 1     |
| cie_avant_3112   | 0     | 7       | 15    |
| cine_avant_3112  | 1     | 7       | 14    |
| cie_courte       | 4     | 0       | 0     |
| cine_courte      | 4     | 0       | 0     |

La bande **avant_3112 concentre les basses confiances** (29/32) : ses feuilles
sont presque toutes des règles `calculatrice` à bornes phénologiques
(date_semis / date_destruction). Le board fige bien un libellé, mais plusieurs
widgets de libellé identique couvrent les variantes ICPE/Q6/effluent qu'on ne
distingue pas par le texte seul.

## Feuilles « basse confiance » — détail par catégorie

### 1. Calculatrice phénologique, plusieurs candidats (27 feuilles)

Bande `avant_3112`, types Ia / Ib / II. Le widget proposé est le meilleur
recoupement, mais 2+ widgets portent les mêmes dates fixes ; les
sous-conditions (ICPE A / enregistrement-déclaration, IAA Q6 vrai/faux,
effluent peu chargé) ne sont pas lisibles dans le texte. La `note` de chaque
ligne liste les `id` candidats. À trancher visuellement sur le board.

Règles concernées (chacune via plusieurs chemins ICPE/Q6) :
`r_cine_avant_3112_type_Ia_*`, `r_cine_avant_3112_type_Ib_*`,
`r_cine_avant_3112_type_II_*`, `r_cie_avant_3112_type_III`.

### 2. Type III « après 01/01 » sans widget dédié (3 feuilles) — PROBLÈME STRUCTUREL

`r_true` (cie_apres_0101 type III),
`r_cie_apres_0101_interculture_longue_type_cie_apres_0101_type_iii_false`,
`r_type_iii` (cine_apres_0101 type III).

**Le board ne dessine aucune feuille-résultat type III dans la bande A
(après 01/01).** Les seuls widgets « Interdit du 01/07 au 30/06 » (id
`3458764674736757828`) et « Interdit du 01/07 … au jour de l'implantation »
(ids `3458764674736757837` / `3458764674736757836`) sont rangés **en haut de
la bande avant_3112** (y ≈ 12169–12443), sous les libellés CIE/CINE + Type III
de cette section. Ils sont donc **potentiellement partagés** entre les deux
sections. `miro_widget_id` laissé vide ; candidats donnés en note. À trancher
juriste (la divergence type III était déjà signalée dans
`../2026-05-30/cross_validation_couvert.md` §2).

### 3. « autre » (2 feuilles)

Comptées dans la catégorie 2 ci-dessus selon le détail des notes
(`r_true`, `r_type_iii` retombent sur la même cause structurelle type III).

## Problèmes structurels rencontrés

1. **Board d'une autre version que l'ancien rapprochement.** Les
   `svg_attendu`/`svg_proche` du `couvert_reference_svg.json` (2026-05-30)
   utilisent un **phrasé différent** du board 2026-06-15 (« Si la date de
   destruction du couvert est plus tôt que le 05/12, … » vs « Dans cette
   période : Interdit du 15/11 jusqu'à 4 semaines après implantation »).
   **Zéro correspondance exacte** entre les deux : l'ancien fichier n'a servi
   que d'indice de recoupement par dates communes.

2. **Duplication massive des feuilles-résultat.** 113 feuilles YAML se
   replient sur un petit nombre de libellés ; le board matérialise chaque
   variante de sous-condition par un widget distinct **au texte identique**.
   Sans modèle complet de la topologie spatiale du board (lui-même ambigu :
   plusieurs widgets-résultat par chemin Type/Q2), le texte seul ne permet
   pas de pointer l'instance exacte → d'où la majorité de « moyenne ».

3. **Type III après 01/01 absent de sa bande** (cf. catégorie 2) : oddité
   structurelle réelle, pas une erreur de matching.

4. **Frontière de bande type III** : les widgets type III « après » et
   « avant » se touchent autour de y ≈ 12200 ; la coupure de bande y a été
   fixée à 12200 et les cas limites traités par garde explicite (type III
   après → pas de widget).

## Reproduire / corriger

- Régénérer les feuilles : `sh dump_leaves.sh` (conteneur Django up).
- Régénérer le mapping : `python3 build_mapping_couvert.py`
  (option `--dump` pour un diagnostic ligne à ligne).
- **Corrections manuelles** : dict `OVERRIDES` en bas de
  `build_mapping_couvert.py` (vide pour l'instant ; à remplir au fil de la
  validation visuelle de Max, chaque entrée documentée). Aucune correction
  manuelle n'a été appliquée à ce jour — tout le mapping est issu du script.
