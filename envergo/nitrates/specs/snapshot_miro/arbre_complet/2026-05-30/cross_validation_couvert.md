# Cross-validation des feuilles « couvert d'interculture »

**Date :** 2026-06-01
**Méthode :** rapprochement direct **SVG + CSV** (export Miro brut de
l'arbre national) ⇄ **YAML actif** (câblage prod) ⇄ **pseudocode.md**
(transcription texte du 2026-05-30, cross-check).

Périmètre : la branche `occupation_sol = couvert_intercultures` du YAML,
soit **113 feuilles** atteignables (renvoi_vers résolus), réparties en
6 sous-cultures :

| sous_culture     | feuilles | libellé board                                   |
|------------------|----------|-------------------------------------------------|
| `cie_apres_0101` | 31       | CIE récolté / toujours en place après 01/01     |
| `cine_apres_0101`| 30       | CINE non récolté après 01/01                    |
| `cie_avant_3112` | 22       | CIE récolté avant le 31/12                      |
| `cine_avant_3112`| 22       | CINE détruit avant le 31/12                     |
| `cie_courte`     | 4        | Couvert courte exporté (dérobée, CIVE)          |
| `cine_courte`    | 4        | Couvert courte non exporté                      |

> Les 113 feuilles YAML se replient sur **43 textes-résultat distincts**
> côté SVG : un même résultat est atteint par plusieurs chemins
> ICPE / IAA / zonage (Q2 plan d'épandage, Q6 IAA, note 5). C'est attendu.

## Niveau de preuve

Contrairement à la culture principale (PNG juriste validés dans
`culture_principale/2026-05-08/index.yaml`), **les feuilles couvert n'ont
pas encore de référence contractuelle**. La seule extraction texte
exhaustive est :

1. l'inventaire SVG/CSV (libellés + périodes + codes PC extraits verbatim
   — **fiable sur l'inventaire**, à recouper sur le câblage) ;
2. le `pseudocode.md` ci-joint (mêmes réserves : ~25 % de connecteurs
   incertains, type II « après 01/01 » dense signalé à confirmer).

C'est précisément ce que la validation manuelle de Max dans la mini-app
(`/admin/nitrates/validation/`) doit trancher. Ce fichier liste les
points à regarder en priorité.

## Concordance globale

- **67 / 113** feuilles : texte YAML ⇄ texte SVG concordant
  (score Jaccard ≥ 0,75 sur la clause principale).
- **35** feuilles sont des règles `calculatrice` **sans `texte` figé** :
  le texte affiché est dérivé des `periodes` relatives (semis /
  implantation / destruction). À comparer visuellement au board, pas par
  texte (d'où les captures Playwright).
- Le reste = 6 familles de règles à clarifier (ci-dessous).

## Bug trouvé et corrigé pendant la validation 🐛✅

**6 feuilles couvert courte cassaient le simulateur (ParcoursError).**

Les branches type 0 / I / II de `cie_courte` et `cine_courte` font
`renvoi_vers: r_cie_courte_types_0_I_II` / `r_cine_courte_types_0_I_II`.
Ces deux règles vivent dans la section `regles_partagees:` du YAML (hors
de l'arbre). Or `parcours._build_id_index()` n'indexait que l'arbre +
`plafonnements`, pas `regles_partagees` → le renvoi ne se résolvait pas
et levait `ParcoursError` sur ces 6 chemins (3 types × CIE/CINE courte).

Vérifié via Playwright : avant le fix, ces URL rendaient un résultat
« non disponible » (et, en remontant, une 500 sur le parcours brut).
Après fix (1 ligne : indexer aussi `regles_partagees`), les 113 feuilles
résolvent (`107→113 ok`, `6→0 ParcoursError`). Régression couverte par
`test_couvert_courte_renvoi_vers_regle_partagee`.

## Divergences à trancher (juriste / Max)

### 1. `r_cine_avant_3112_type_0_icpe_a` — divergence réelle ⚠️

- **YAML** : « Autorisation dans les conditions de la note 1. Sinon
  interdiction du 15/12 au 15/01. »
- **SVG / CSV** (CINE avant 31/12, Type 0, Q2 = à autorisation, PC1
  « ICPE A ») : « Autorisé sous condition entre le 15/12 et le 15/01 »
  (+ motifs calculatrice implantation/destruction).

La formulation « conditions de la note 1 » (note 1 = ICPE A + type de
fertilisant + IAA, cf. CSV ligne 67) **n'apparaît nulle part** dans les
feuilles-résultat du board.

**Vérif Playwright :** le simulateur affiche bien la **période** correcte
en titre (« autorisé sous condition du 15/12 au 15/01 », = board) ; la
phrase « note 1 » n'est que le **texte de condition** sous le calendrier.
Donc pas de contradiction de routage — c'est une question de
**formulation de la condition** (la note 1 est-elle le bon libellé à
afficher ?). À trancher rédaction, pas bug.

### 2. `r_cine_avant_3112_type_III` — divergence réelle ⚠️

- **YAML** : « Apport interdit toute l'année. »
- **SVG / pseudocode** : aucune feuille « toute l'année » pour CINE
  avant 31/12 Type III. Le board décline plutôt des motifs calculatrice
  (15/10 ou 15/11 → 15/01 selon zonage). À vérifier sur le board : la
  feuille Type III de cette famille est-elle vraiment « toute l'année »
  ou un motif daté ?

### 3–6. Familles « courte » — écart de formulation seulement ✓(à confirmer)

Le matcher a mal scoré ces 4 règles parce qu'il les a comparées à la
mauvaise bande du board (longue). Recoupées à la zone courte du SVG/CSV
(lignes 444-462) et au pseudocode B.2, **la sémantique concorde** ; seule
la formulation diffère :

| règle YAML                  | YAML                                                              | SVG / CSV (B.2)                                                               |
|-----------------------------|-------------------------------------------------------------------|------------------------------------------------------------------------------|
| `r_cine_courte_types_0_I_II`| « Apport autorisé. »                                              | « Apport autorisé » [PC13]                                                    |
| `r_cie_courte_types_0_I_II` | « Apport autorisé selon les conditions du PAR. »                  | « Apport autorisé » [PC15] (YAML précise « selon PAR »)                       |
| `r_cine_courte_type_III`    | « Apport interdit. »                                              | « Apport interdit »                                                           |
| `r_cie_courte_type_III`     | « Apports possibles selon le PAR ou entre le semis et les 15 j »  | « Apports interdits **sauf** entre le semis et les 15 j suivants » (négatif)  |

→ `r_cie_courte_type_III` : même périmètre exprimé en positif (YAML) vs
négatif (SVG). À harmoniser côté rédaction.

## Points ouverts hérités du board (rappel)

- **Type II « après 01/01 »** (≈30 feuilles, la zone la plus dense) :
  câblage Q2 / Q6 / effluents peu chargés / zonage à confirmer sur le
  board — inventaire des feuilles complet, arbre de décision à valider.
- **Flèches violettes « go to CINE avant 31/12 »** depuis la courte CINE :
  sémantique du renvoi à confirmer (déjà câblée en `renvoi_vers` dans le
  YAML).

## Traçabilité dans l'app de validation (flags)

Pour ne pas perdre la trace des points ci-dessus lors de la
re-validation humaine, le seed pose un **flag `flag_verif` + note
`note_verif`** sur les `BrancheValidation` concernées. Visible dans
l'app : pilule « ⚑ à vérifier » dans l'index (+ liseré rouge sur la
ligne), encart rouge éditable dans le détail.

Répartition au seed (46 feuilles flaggées sur 113) :

| catégorie                         | n  | sens                                                    |
|-----------------------------------|----|---------------------------------------------------------|
| calculatrice sans texte figé      | 35 | comparer le calendrier au board (pas de match texte)    |
| ex-bug `regles_partagees` corrigé | 6  | re-vérifier le rendu des courtes 0/I/II après fix       |
| formulation à trancher            | 3  | note 1 (×2 chemins) + cie_courte type III positif/négatif|
| divergence board                  | 1  | `r_cine_avant_3112_type_III` « toute l'année »          |
| rapprochement SVG faible          | 1  | texte board incertain                                   |

Le flag est éditable dans le détail (décocher = lever). **Mais un
re-seed le repose** (c'est une note de seed, pas une saisie humaine) —
cf. docstring de `seed_branches_validation_couvert`.

## Fichiers

- `couvert_reference_svg.json` — table des 113 feuilles : `chemin_yaml`,
  contexte (sous_culture, type, plan_epandage, IAA, note 5), texte YAML,
  **texte attendu SVG**, score de rapprochement. Source du seed
  `BrancheValidation` couvert.
