# Arbre de décision NATIONAL — transcription pseudo-code (si / alors)

**Source :** `arbre_decision_complet.svg` (export Miro du 2026-05-30).
**Méthode :** extraction automatique des 286 nœuds + 432 connecteurs du
SVG (texte + coordonnées), puis reconstruction de la hiérarchie par
position (l'arbre se lit gauche→droite, haut→bas) et recoupement avec
les connecteurs.

## /!\ Niveau de fiabilité — À LIRE AVANT D'EN FAIRE DES TESTS

Conformément à la hiérarchie de `snapshot_miro/README.md` (point 2),
**un export Miro SVG est de l'inventaire, PAS un contrat de test.** La
ponctuation, les accents, l'ordre et surtout le **routage des
connecteurs** se déforment à l'export. Cette transcription est donc :

- **fiable** sur l'inventaire : libellés des feuilles, périodes, codes
  PC, structure générale des branches (tout cela est du texte extrait
  verbatim du SVG) ;
- **à recouper** sur le câblage fin question→feuille : ~25 % des
  connecteurs n'ont pas pu être rattachés géométriquement de façon
  certaine (longues arêtes coudées, sauts « go to » violets). Là où
  j'ai dû déduire le parent d'une feuille par sa colonne / sa bande
  verticale, c'est signalé.

**Ce qui fait foi :**
1. pour **culture principale** → `../../culture_principale/2026-05-08/index.yaml`
   (snapshot PNG validé juriste). La transcription ci-dessous a été
   **recoupée avec succès** contre ce fichier (mêmes feuilles, mêmes
   périodes, mêmes codes PC) — voir § Recoupement.
2. pour **ce qui tourne en prod** → `../../../arbre_decision_national.yaml`.
3. pour les branches **couvert** (longue / courte), non encore
   snapshottées en feuille fine ailleurs : **cette transcription est
   pour l'instant la seule extraction texte exhaustive**, à valider
   avec le juriste avant d'en faire un `index.yaml` contractuel.

## Légende des couleurs (panneau #60 du board)

- vert  = info localisation (a priori pas de question posée)
- bleu  = question de 1er niveau / option occupation du sol
- violet = option fertilisant
- jaune = question de 2nd niveau (question secondaire à poser)
- rouge = période d'**interdiction** à afficher
- orange foncé = période d'**autorisation sous condition** à afficher
- gris = prescriptions conditionnées (codes PC), affichées sous les
  périodes d'interdiction

## Vocabulaire

- **Type 0 / I / Ia / Ib / II / III** = types de fertilisant.
- **Note 5** = PACA, Occitanie + Dordogne (24), Gironde (33), Landes
  (40), Lot-et-Garonne (47), Pyrénées-Atlantiques (64).
- **Note 6** = autre région et/ou départements (complémentaire note 7).
- **Note 7** = PACA, Occitanie + Pyrénées-Atlantiques.
- **CINE** = couvert d'interculture non exporté. **CIE** = couvert
  d'interculture exporté (dérobée, CIVE). **CIVE** = culture
  intermédiaire à vocation énergétique.
- Codes PC (prescriptions) cités dans cet arbre :
  PC1 ICPE A · PC2 IAA + ICPE A · PC3 IAA + ICPE D ou E ·
  PC4 non ICPE A · PC5 culture irriguée · PC6 effluents peu chargés en
  fertirrigation · PC7 effluent peu chargé · PC8 effluent peu chargé
  élevage + non ICPE A · PC9 effluent peu chargé élevage + non ICPE A ·
  PC10 IAA luzerne + ICPE A · PC11 colza · PC13 plafond CINE détruit
  avant 31/12 · PC15 plafond CIE courte.

---

# RACINE

```
SI parcelle PAS en zone vulnérable (ZV)              -> NON APPLICABLE (réglementation ne s'applique pas)
SI parcelle EN zone vulnérable                       -> question occupation_sol
```

```
question occupation_sol "La culture en place est une culture principale
                         ou un couvert végétal d'interculture ?"
  -> Sol non cultivé          -> Interdit du 01/07 au 30/06 (toute l'année)
  -> Culture principale       -> [BRANCHE A]
  -> Couvert végétal d'interculture -> [BRANCHE B]
```

---

# BRANCHE A — CULTURE PRINCIPALE

Sous-question : **quelle culture principale ?** (colza / culture d'hiver
autre que colza / culture de printemps / prairies >6 mois / luzerne /
autres cultures). Puis pour chacune : **quel type de fertilisant ?**

> Ces 6 sous-branches sont déjà transcrites et **validées juriste** dans
> `../../culture_principale/2026-05-08/index.yaml`. Repris ici en
> pseudo-code pour la complétude ; ce fichier index.yaml fait foi.

## A.1 — Colza

```
SI Type 0                         -> Interdit du 15/12 au 15/01
SI Type I                         -> Interdit du 15/11 au 15/01
SI Type II  ET Note 5             -> Interdit du 15/10 au 15/01
SI Type II  ET pas Note 5         -> Interdit du 15/10 au 31/01
SI Type III ET Note 5             -> Autorisé sous condition du 01/09 au 15/10 et Interdit du 15/10 au 15/01   [PC11]
SI Type III ET pas Note 5         -> Autorisé sous condition du 01/09 au 15/10 et Interdit du 15/10 au 31/01   [PC11]
```

## A.2 — Culture d'hiver autre que colza

```
SI Type 0                         -> Interdit du 15/12 au 15/01
SI Type I                         -> Interdit du 15/11 au 15/01
SI Type II  ET Note 5             -> Interdit du 01/10 au 15/01
SI Type II  ET pas Note 5         -> Interdit du 01/10 au 31/01
SI Type III ET Note 5             -> Interdit du 01/09 au 15/01
SI Type III ET pas Note 5         -> Interdit du 01/09 au 31/01
```

## A.3 — Culture de printemps

```
SI Type 0                                              -> Interdit du 15/12 au 15/01
SI Type Ia                                             -> Interdit du 01/07 au 31/08 puis du 15/11 au 15/01
SI Type Ib                                             -> Interdit du 01/07 au 15/01
SI Type II  ET effluents peu chargés (Q3 fertirrigation = Oui) -> Interdit du 31/08 au 31/01 et autorisé sous condition entre le 01/07 et le 31/08   [PC6]
SI Type II  ET effluents peu chargés (Q3 fertirrigation = Non) -> Interdit du 01/07 au 31/01
SI Type III ET Q4 culture irriguée = Oui / Maïs        -> Interdit du 15/07 au 15/02, autorisé sous condition entre 15/07 et le stade du brunissement des soies du maïs   [PC5]
SI Type III ET Q4 culture irriguée = Oui / Autre       -> Interdit du 15/07 au 15/02   [PC5]
SI Type III ET Q4 culture irriguée = Non               -> Interdit du 01/07 au 15/02
```

## A.4 — Prairies implantées depuis plus de 6 mois (dont prairie permanente)

```
SI Type 0  ET Q1 Plan d'épandage = à autorisation      -> Autorisé sous condition entre le 15/12 et le 15/01   [PC1]
SI Type 0  ET Q1 Plan d'épandage = autres              -> Interdit du 15/12 au 15/01
SI Type I                                              -> Interdit du 15/12 au 15/01
SI Type II ET effluents peu chargés = Oui              -> Autorisé sous condition entre le 15/11 et le 15/01   [PC7]
SI Type II ET effluents peu chargés = Non              -> Interdit du 15/11 au 15/01
SI Type III ET îlot en zone montagne (D113-14 CRPM) = Oui ET Note 7 -> Interdit du 01/10 au 15/02
SI Type III ET îlot en zone montagne (D113-14 CRPM) = Oui ET Note 6 -> Interdit du 01/10 au 28/02
SI Type III ET îlot en zone montagne = Non             -> Interdit du 01/10 au 15/01
```

## A.5 — Luzerne

```
SI Type 0                                                              -> go to branche prairie + type 0
SI Type I  ET Q1 = à autorisation ET Q3 IAA (note 12) = oui            -> Autorisé sous conditions après la dernière coupe de luzerne. Sinon interdit du 15/12 au 15/01   [PC10]
SI Type I  ET Q1 = à autorisation ET Q3 IAA = non                      -> Interdit du 15/12 au 15/01
SI Type I  ET Q1 = autre                                               -> Interdit du 15/12 au 15/01
SI Type II ET Q1 = à autorisation ET Q3 IAA = oui                      -> Autorisé sous conditions après la dernière coupe de luzerne. Sinon interdit du 15/11 au 15/01   [PC10]
SI Type II ET Q1 = à autorisation ET Q3 IAA = non                      -> go to branche prairie + type II
SI Type II ET Q1 = autre                                               -> go to branche prairie + type II
SI Type III ET Q1 = à autorisation ET Q3 IAA = oui ET montagne = oui ET Note 7 -> Autorisé sous conditions après la dernière coupe de luzerne. Sinon interdit du 01/10 au 15/02   [PC10]
SI Type III ET Q1 = à autorisation ET Q3 IAA = oui ET montagne = oui ET Note 6 -> Autorisé sous conditions après la dernière coupe de luzerne. Sinon interdit du 01/10 au 28/02   [PC10]
SI Type III ET Q1 = à autorisation ET Q3 IAA = oui ET montagne = non           -> Autorisé sous conditions après la dernière coupe de luzerne. Sinon interdit du 01/10 au 31/01   [PC10]
SI Type III ET Q1 = à autorisation ET Q3 IAA = non                             -> go to branche prairie + type III
SI Type III ET Q1 = autre                                                      -> go to branche prairie + type III
```

## A.6 — Autres cultures (pérennes-vergers, vignes, maraîchères, porte-graine)

```
SI Types 0, Ia, Ib, II ou III     -> Interdit du 15/12 au 15/01   (feuille unique, tous types)
```

---

# BRANCHE B — COUVERT VÉGÉTAL D'INTERCULTURE

> **NON snapshotté en feuille fine ailleurs.** Cette section est la
> seule extraction texte exhaustive à ce jour — à valider juriste.

Le board sépare d'abord la **durée** de l'interculture :

```
question couvert
  -> Couvert d'interculture LONGUE   -> [B.1]
  -> Couvert d'interculture COURTE   -> [B.2]
```

Pour la longue, deux familles selon la date de destruction/export :

```
Couvert d'interculture longue
  -> CINE détruit ou CIE exporté APRÈS le 01/01 (dont CIVE)  -> [B.1.a]
  -> CINE détruit AVANT le 31/12                              -> [B.1.b]
```

Toutes les feuilles « couvert » utilisent le composant **Calculatrice
Calendrier Dynamique** (périodes relatives au semis / à l'implantation /
à la destruction du couvert). Les motifs qui reviennent :

- `Interdit avant 4 semaines après implantation du couvert` (borne basse)
- `interdit à partir de 20j avant la récolte/destruction du couvert` (borne haute)
- `Si la date de destruction du couvert est plus tôt que le <pivot>, …`
  (prescription **conditionnelle** sur la date de destruction — pivot
  **05/12** pour la famille « avant 31/12 » longue, **04/11** pour la
  famille courte CINE)

## B.1.a — Couvert longue, CINE détruit / CIE exporté APRÈS le 01/01 (dont CIVE)

Structure par type de fertilisant. Pour les types avec ICPE, sous-arbre
**Q2 plan d'épandage** (à autorisation → ICPE A ; à enregistrement ou
déclaration → ICPE D/E) puis **Q6 IAA** (fertilisant issu de traitement/
transformation pour alimentation humaine/animale, vins, distillation).

```
SI Type 0  ET Q2 = à autorisation (ICPE A)                  -> Autorisé sous condition entre le 15/12 et le 15/01 (interdit avant 4 sem. après implantation ; interdit dès 20j avant récolte/destruction)   [PC?]
SI Type 0  ET Q2 = enregistrement/déclaration ET Q6 = oui   -> Autorisé sous condition entre le 15/12 et le 15/01 (idem)   [PC3 IAA + ICPE D ou E]
SI Type 0  ET Q2 = enregistrement/déclaration ET Q6 = non   -> Interdiction du 15/12 au 15/01

SI Type I  ET … (sous-arbre Q2/Q6 analogue)                 -> Autorisé sous condition entre le 15/11 et le 15/01 (idem motifs)   [PC2 / PC3 / PC4 selon ICPE]
SI Type I  ET branche « non autorisée »                     -> Interdit du 15/11 au 15/01 (autorisé sous condition jusqu'à 20j avant destruction/récolte)   [PC4 non ICPE A]
SI Type I  ET Q6 = non                                      -> Interdiction du 15/11 au 15/01

SI Type II ET effluents peu chargés issus d'élevage / non issus d'élevage (sous-arbre)
           -> Autorisé sous condition entre le 15/10 et le 15/01 / au 31/01 selon zonage (idem motifs)   [PC2 / PC3]
           -> Autorisé sous condition entre le 15/10 et le 15/11. Interdit entre le 15/11 et le 15/01 (ou au 31/01)   [PC8 effluent peu chargé élevage + non ICPE A]
           -> Interdit entre le 15/10 et le 15/01 (ou 31/01) et autorisé pendant cette période sous condition jusqu'à 20j avant destruction/récolte   [PC4 non ICPE A]
           -> Interdit du 15/10 au 15/01 (ou 31/01). Dans cette période : autorisé sous condition jusqu'à 20j avant destruction/récolte   [PC4 non ICPE A]
```

> **À recouper juriste :** le câblage exact type II → {Q2, Q6, effluents
> peu chargés, zonage} de cette famille est le plus dense de l'arbre
> (≈ 30 feuilles entre y=4900 et y=9900 du board) et c'est là que les
> connecteurs sont les moins fiables à l'extraction. L'inventaire des
> **feuilles** (libellés + PC ci-dessus) est complet ; l'arbre de
> décision qui y mène est à confirmer sur le PNG/board.

Deux feuilles « hors calculatrice » de cette famille (semis comme borne) :

```
-> Apport interdit à partir de 15 jours après le semis jusqu'au 15/01
-> Apport interdit à partir de 15 jours après le semis jusqu'au 31/01
```

## B.1.b — Couvert longue, CINE détruit AVANT le 31/12

Même ossature, mais ajout systématique de la **prescription
conditionnelle sur la date de destruction** (pivot **05/12**) :

```
SI Type 0  ET Q2 = à autorisation                 -> Autorisé sous condition entre le 15/12 et le 15/01 (motifs calculatrice)
SI Type 0  ET Q2 = enreg./décl. ET Q6 = oui        -> Autorisé sous condition entre le 15/12 et le 15/01   [PC3]
SI Type 0  ET Q2 = enreg./décl. ET Q6 = non        -> Interdiction du 15/12 au 15/01

SI Type I  ET … (Q6=oui, ICPE A)  -> Autorisé sous condition entre le 15/11 et le 15/01.
                                     SI destruction plus tôt que le 05/12 : autorisé sous condition dès 20j avant destruction jusqu'au 15/01
                                     (+ motifs calculatrice)
SI Type I  ET branche non-ICPE-A  -> Interdit du 15/11 au 15/01.
                                     SI destruction plus tôt que le 05/12 : interdit dès 20j avant destruction jusqu'au 15/01.
                                     Dans la période d'interdiction : autorisé sous condition jusqu'à 20j avant destruction/récolte   [PC4]

SI Type II / III  -> mêmes 2 motifs (autorisé/interdit) + pivot 05/12, déclinés selon Q6 / ICPE :
   - CINE : "Pas d'apport avant 15 jours avant l'implantation du CINE. Puis interdit du 15/11 au 15/01.
             SI destruction plus tôt que le 05/12 : interdit dès 20j avant destruction jusqu'au 15/01."   [PC2/PC4]
   - "Autorisé sous condition avant 15j avant l'implantation du couvert et entre le 15/11 et le 15/01.
      SI destruction plus tôt que le 05/12 : autorisé sous condition dès 20j avant destruction jusqu'au 15/01."   [PC2]
```

> **Recoupement code :** c'est exactement le motif `condition:
> date_destruction_couvert >= 05/12` / `< 05/12` que l'on retrouve dans
> les nœuds calculatrice `cine_avant_3112` du YAML (type_0 / type_Ia /
> type_Ib / type_II). Le pivot **05/12** ici, **04/11** pour la famille
> courte (voir B.2), est cohérent avec l'implémentation actuelle.

## B.2 — Couvert d'interculture COURTE

Deux sous-branches selon export :

```
Couvert d'interculture courte
  -> Couvert Non Exporté (CINE)            -> [B.2.a]
  -> Couvert Exporté (dérobée, CIVE) (CIE) -> [B.2.b]
```

### B.2.a — CINE (non exporté), courte

```
SI Types 0, I ou II   -> Apport interdit
SI Type III           -> Interdit avant le semis et à partir de 15 jours après le semis jusqu'au 31 janvier   (calculatrice)
```

Plus, rattachés à cette branche, des sauts vers la famille « avant
31/12 » (réutilisation des feuilles longue B.1.b) :

```
-> go to CINE détruit avant le 31/12 Type 0
-> go to CINE détruit avant le 31/12 Type Ia
-> go to CINE détruit avant le 31/12 Type Ib
-> go to CINE détruit avant le 31/12 Type II
```

> **À trancher juriste (point ouvert connu) :** ces « go to » CINE
> courte → CINE avant-31/12 correspondent aux **flèches violettes**
> repérées sur le board (double flèche CIE). Sémantique exacte du
> renvoi à confirmer.

### B.2.b — CIE (exporté : dérobée, CIVE), courte — « CIE récolté avant le 31/12 »

```
SI Types 0, I ou II   -> Apport autorisé                                                                    [PC15 plafond CIE courte]
SI Type III           -> Apports interdits sauf entre le semis du couvert et les 15 jours suivant le semis   [PC15 plafond CIE courte]
```

Et la prescription plafond pour la variante CINE détruit avant 31/12 :

```
-> Apport autorisé   [PC13 plafond CINE détruit avant 31/12]
```

---

# Questions secondaires (panneau de spec #49-54 du board)

Catalogue des questions « supplémentaires » (max 2 posées) référencées
par les branches ci-dessus :

- **Q1** Parcelle soumise à un plan d'épandage ? → Pas concerné / à
  autorisation (ICPE A) / à enregistrement (ICPE E) / à déclaration (ICPE D)
- **Q2** Voulez-vous épandre avec des effluents peu chargés ?
- **Q3** Voulez-vous épandre avec des effluents peu chargés en fertirrigation ?
- **Q4** Votre culture est-elle irriguée ?
- **Q5** culture irriguée ? (variante posée en culture de printemps)
- **Q6** Le fertilisant est-il issu de traitement/transformation de
  matières premières (alimentation humaine/animale, vins, distillation
  d'alcools de bouche) — c.-à-d. IAA ? (note 12)

---

# Recoupement (auto, SVG ↔ index.yaml culture_principale)

Les 6 branches culture principale extraites du SVG correspondent
feuille-à-feuille à `culture_principale/2026-05-08/index.yaml` : mêmes
types de fertilisant, mêmes périodes (15/12–15/01, 01/10–31/01, etc.),
mêmes codes PC (PC1, PC5, PC6, PC7, PC10, PC11), mêmes zonages (Note 5,
6, 7). Aucune divergence détectée sur cette branche → l'extraction SVG
est jugée fidèle là où elle est vérifiable.

Les branches **couvert** (B.1 / B.2) n'ont pas de référence validée à
recouper : elles restent **à valider juriste** avant tout usage en test.
