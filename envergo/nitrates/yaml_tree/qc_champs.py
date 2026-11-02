"""Questions complementaires (QC) : identite, recherche et normalisation des
champs (carte #620).

Une QC est un noeud `formulaire` de niveau `complement`. Sa reponse est rangee
dans le contexte de parcours sous son `champ`, et c'est ce champ (lui seul)
qui fait qu'une question deja repondue n'est pas reposee plus loin, y compris
d'un arbre a l'autre de la cascade (ZAR -> PAR -> PAN). Deux noeuds qui posent
la meme question sous deux champs differents la font donc poser deux fois.

Ce module, sans dependance Django, fournit :
  - la collecte des QC d'un arbre (`collecter_qc`) ;
  - la recherche tolerante d'une QC existante a partir d'un texte saisi
    (`catalogue_qc`, `rechercher_qc`), pour l'editeur admin ;
  - le plan de normalisation (`planifier_normalisation`) : meme texte affiche
    + memes reponses possibles => meme champ ;
  - la reecriture d'un arbre selon ce plan (`renommer_champs`), references
    comprises (expressions des catalogues parametres, remap de contexte).
"""

from __future__ import annotations

import ast
import copy
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Iterable

# Mots trop frequents pour discriminer deux questions (recherche seulement :
# l'identite d'une question, elle, porte sur le texte complet).
_MOTS_VIDES = frozenset(
    "a au aux avec ce ces cet cette d dans de des du en est et il ils l la le "
    "les leur leurs ou par pas pour qu que qui s sa se ses son sont sur un une "
    "vos votre vous y est-ce".split()
)

_VRAI = ("true",)
_FAUX = ("false",)
_LIBELLES_VRAI = ("oui", "true", "vrai")
_LIBELLES_FAUX = ("non", "false", "faux")


# ─── Normalisation ──────────────────────────────────────────────────────────


def normaliser_texte(texte: str | None) -> str:
    """Texte reduit a ses mots : minuscules, sans accents ni ponctuation.

    Deux redactions qui ne different que par la ponctuation, la casse, les
    espaces ou un accent oublie designent la meme question."""
    s = unicodedata.normalize("NFD", str(texte or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^\w\s]", " ", s).lower().split())


def cle_valeur(valeur: Any) -> str:
    """Forme comparable d'une valeur de branche.

    Meme tolerance que le parcours (`_valeurs_egales`) : le booleen True et la
    chaine 'True' designent la meme reponse."""
    if isinstance(valeur, bool):
        return "true" if valeur else "false"
    s = str(valeur)
    if s.strip().lower() in _VRAI + _FAUX:
        return s.strip().lower()
    return s


def _valeurs_branche(branche: dict) -> list:
    if "valeurs" in branche and isinstance(branche.get("valeurs"), list):
        return list(branche["valeurs"])
    if "valeur" in branche:
        return [branche["valeur"]]
    return []


# ─── Collecte ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OccurrenceQC:
    """Un noeud QC d'un arbre."""

    arbre: str
    noeud_id: str
    champ: str
    texte: str
    aide: str | None = None
    # (valeur, libelle) dans l'ordre du YAML.
    branches: tuple = ()
    arbre_pk: int | None = None

    @property
    def texte_norm(self) -> str:
        return normaliser_texte(self.texte)

    @property
    def valeurs(self) -> frozenset:
        return frozenset(cle_valeur(v) for v, _ in self.branches)

    @property
    def cle(self) -> tuple:
        """Identite de la question telle que l'utilisateur la lit : texte
        affiche + reponses possibles."""
        return (self.texte_norm, self.valeurs)

    @property
    def polarite_inversee(self) -> bool:
        """True si une branche booleenne porte le libelle contraire de sa
        valeur (True libelle « Non »). Fusionner ce champ avec un autre
        inverserait la reponse : on ne le fait jamais."""
        for valeur, libelle in self.branches:
            cv = cle_valeur(valeur)
            lib = normaliser_texte(libelle)
            if cv == "true" and lib in _LIBELLES_FAUX:
                return True
            if cv == "false" and lib in _LIBELLES_VRAI:
                return True
        return False


def iter_noeuds(contenu: dict) -> Iterable[dict]:
    """Tous les noeuds de l'arbre (racine comprise), en profondeur."""
    racine = ((contenu or {}).get("arbre") or {}).get("noeud")
    pile = [racine] if isinstance(racine, dict) else []
    while pile:
        noeud = pile.pop()
        yield noeud
        for branche in reversed(noeud.get("branches") or []):
            if isinstance(branche, dict) and isinstance(branche.get("noeud"), dict):
                pile.append(branche["noeud"])


def est_qc(noeud: dict) -> bool:
    return (
        isinstance(noeud, dict)
        and noeud.get("type_noeud") == "formulaire"
        and noeud.get("niveau") == "complement"
    )


def occurrence_depuis_noeud(
    noeud: dict, arbre: str = "", arbre_pk: int | None = None
) -> OccurrenceQC:
    branches = []
    for b in noeud.get("branches") or []:
        if not isinstance(b, dict):
            continue
        for v in _valeurs_branche(b):
            branches.append((v, b.get("libelle")))
    return OccurrenceQC(
        arbre=arbre,
        noeud_id=str(noeud.get("id") or ""),
        champ=str(noeud.get("champ") or ""),
        texte=" ".join(str(noeud.get("texte") or "").split()),
        aide=noeud.get("aide") or None,
        branches=tuple(branches),
        arbre_pk=arbre_pk,
    )


def collecter_qc(
    contenu: dict, arbre: str = "", arbre_pk: int | None = None
) -> list[OccurrenceQC]:
    """Les QC d'un arbre, dans l'ordre de lecture."""
    return [
        occurrence_depuis_noeud(n, arbre, arbre_pk)
        for n in iter_noeuds(contenu)
        if est_qc(n) and n.get("champ")
    ]


# ─── Recherche (editeur admin) ──────────────────────────────────────────────


@dataclass
class QcExistante:
    """Une question deja posee quelque part, telle que l'editeur la propose :
    un champ, un texte, ses reponses, et les arbres ou elle apparait."""

    champ: str
    texte: str
    aide: str | None
    branches: list[dict]  # [{valeur, libelle}]
    occurrences: list[OccurrenceQC] = field(default_factory=list)

    @property
    def arbres(self) -> list[str]:
        vus: list[str] = []
        for o in self.occurrences:
            if o.arbre not in vus:
                vus.append(o.arbre)
        return vus

    @property
    def nb_occurrences(self) -> int:
        return len(self.occurrences)


def catalogue_qc(occurrences: Iterable[OccurrenceQC]) -> list[QcExistante]:
    """Regroupe les occurrences par (champ, reponses possibles) : une entree
    par question reutilisable, avec ses lieux d'usage.

    Les variantes de redaction d'un meme champ (virgule, « du traitement et/ou
    de la transformation »...) ne font qu'une entree : on affiche la redaction
    la plus utilisee, et les libelles de reponse qui vont avec."""
    groupes: dict[tuple, list[OccurrenceQC]] = defaultdict(list)
    for o in occurrences:
        groupes[(o.champ, o.valeurs)].append(o)
    out: list[QcExistante] = []
    for (champ, _), occs in groupes.items():
        texte_norm = Counter(o.texte_norm for o in occs).most_common(1)[0][0]
        memes = [o for o in occs if o.texte_norm == texte_norm]
        modele = memes[0]
        branches = Counter(o.branches for o in memes).most_common(1)[0][0]
        out.append(
            QcExistante(
                champ=champ,
                texte=modele.texte,
                aide=next((o.aide for o in memes if o.aide), None),
                branches=[{"valeur": v, "libelle": lib} for v, lib in branches],
                occurrences=list(occs),
            )
        )
    return out


def _racine(mot: str) -> str:
    """Racine grossiere : pluriel retire (« produits » = « produit »)."""
    if len(mot) > 4 and mot[-1] in "sx":
        return mot[:-1]
    return mot


def _mots(texte: str) -> list[str]:
    return [
        _racine(m)
        for m in normaliser_texte(texte).split()
        if m not in _MOTS_VIDES and len(m) > 1
    ]


def score_recherche(saisie: str, texte: str) -> float:
    """Ressemblance entre une saisie (eventuellement partielle, en cours de
    frappe) et le texte d'une question existante, entre 0 et 1.

    On combine deux lectures :
      - la proportion des mots saisis qu'on retrouve dans la question (le
        dernier mot peut etre incomplet : il matche en prefixe) ;
      - la ressemblance caractere a caractere des deux textes entiers, pour
        les reformulations proches.
    """
    ns, nt = normaliser_texte(saisie), normaliser_texte(texte)
    if not ns or not nt:
        return 0.0
    if ns == nt:
        return 1.0
    # 1.0 est reserve au texte identique : une question reformulee, meme
    # tres proche, reste en dessous (l'editeur l'affiche differemment).
    ratio = SequenceMatcher(None, ns, nt).ratio()
    mots_saisie = _mots(saisie)
    mots_texte = set(_mots(texte))
    if not mots_saisie or not mots_texte:
        return min(0.99, ratio)
    trouves = 0
    for i, m in enumerate(mots_saisie):
        dernier = i == len(mots_saisie) - 1
        if m in mots_texte or (
            dernier and len(m) >= 3 and any(t.startswith(m) for t in mots_texte)
        ):
            trouves += 1
    couverture = trouves / len(mots_saisie)
    jaccard = trouves / len(set(mots_saisie) | mots_texte)
    return min(0.99, max(ratio, 0.75 * couverture + 0.25 * jaccard))


def rechercher_qc(
    saisie: str,
    catalogue: list[QcExistante],
    limite: int = 6,
    seuil: float = 0.5,
) -> list[tuple[float, QcExistante]]:
    """QC existantes qui ressemblent a la saisie, les plus proches d'abord
    (a score egal, les plus utilisees)."""
    if len(normaliser_texte(saisie)) < 3:
        return []
    resultats = []
    for qc in catalogue:
        score = score_recherche(saisie, qc.texte)
        if score >= seuil:
            resultats.append((score, qc))
    resultats.sort(key=lambda r: (-r[0], -r[1].nb_occurrences, r[1].champ))
    return resultats[:limite]


# ─── Plan de normalisation ──────────────────────────────────────────────────


@dataclass
class GroupeNormalisation:
    """Des champs qui posent la meme question et vont fusionner."""

    canonique: str
    champs: list[str]
    occurrences: list[OccurrenceQC]
    compte_par_champ: dict[str, int]

    @property
    def renommages(self) -> dict[str, str]:
        return {c: self.canonique for c in self.champs if c != self.canonique}

    @property
    def textes(self) -> list[str]:
        vus: list[str] = []
        for o in self.occurrences:
            if o.texte not in vus:
                vus.append(o.texte)
        return vus


@dataclass
class PlanNormalisation:
    groupes: list[GroupeNormalisation] = field(default_factory=list)
    # Champs ecartes : polarite inversee (libelle contraire de la valeur).
    ecartes_polarite: dict[str, list[OccurrenceQC]] = field(default_factory=dict)
    # Meme champ, jeux de reponses differents selon les noeuds.
    valeurs_divergentes: dict[str, list[tuple[frozenset, list[OccurrenceQC]]]] = field(
        default_factory=dict
    )
    # Champs distincts aux textes proches (pas identiques) et aux memes
    # reponses : a trancher a la main (option --fusionner).
    proches: list[tuple[str, str, float]] = field(default_factory=list)

    @property
    def mapping(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for g in self.groupes:
            out.update(g.renommages)
        return out


class PlanImpossible(ValueError):
    """Une contrainte demandee (fusion forcee, canonique force) est
    incompatible avec les arbres."""


def score_descriptif(champ: str) -> int:
    """Plus c'est haut, plus le nom parle a un humain. Penalise les noms
    techniques (`q_...`), les numeros de type (`type_ii`), les majuscules et
    chiffres, et la forme negative (`pas_...`)."""
    score = 0
    if champ.startswith(("q_", "n_")):
        score -= 4
    if re.fullmatch(r"type_[ivx]+[ab]?", champ, flags=re.IGNORECASE):
        score -= 4
    if any(c.isupper() for c in champ):
        score -= 2
    if re.search(r"\d", champ):
        score -= 2
    if champ.startswith("pas_"):
        score -= 1
    return score


class _UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def planifier_normalisation(
    occurrences: list[OccurrenceQC],
    canoniques_forces: Iterable[str] = (),
    exclus: Iterable[str] = (),
    fusions: Iterable[Iterable[str]] = (),
    seuil_proches: float = 0.6,
) -> PlanNormalisation:
    """Calcule les fusions de champs.

    Regle : meme texte affiche (normalise) + memes reponses possibles => meme
    champ. Le regroupement est transitif : un champ qui porte deux variantes
    de texte relie tous les champs qui partagent l'une d'elles.

    Canonique d'un groupe : celui force par `canoniques_forces`, sinon le plus
    utilise (nombre de noeuds), a egalite le plus descriptif, puis l'ordre
    alphabetique (determinisme).

    `exclus` : champs a ne jamais renommer ni absorber.
    `fusions` : groupes de champs a fusionner en plus (textes differents mais
    meme question, decision humaine). Leurs reponses doivent etre identiques.
    """
    exclus = set(exclus)
    plan = PlanNormalisation()

    par_champ: dict[str, list[OccurrenceQC]] = defaultdict(list)
    for o in occurrences:
        par_champ[o.champ].append(o)

    # Meme champ, reponses differentes : signale, jamais corrige ici.
    for champ, occs in par_champ.items():
        jeux: dict[frozenset, list[OccurrenceQC]] = defaultdict(list)
        for o in occs:
            jeux[o.valeurs].append(o)
        if len(jeux) > 1:
            plan.valeurs_divergentes[champ] = sorted(
                jeux.items(), key=lambda kv: (-len(kv[1]), sorted(kv[0]))
            )

    # Polarite inversee : le champ entier est ecarte (renommer le champ
    # renommerait aussi ses autres noeuds).
    for champ, occs in par_champ.items():
        inverses = [o for o in occs if o.polarite_inversee]
        if inverses:
            plan.ecartes_polarite[champ] = inverses
    ecartes = exclus | set(plan.ecartes_polarite)

    uf = _UnionFind()
    for o in occurrences:
        if o.champ in ecartes:
            continue
        uf.find(o.champ)
        uf.union(o.champ, "\x00" + repr(sorted(o.cle[1])) + "\x00" + o.cle[0])

    for groupe in fusions:
        groupe = [c for c in groupe if c]
        inconnus = [c for c in groupe if c not in par_champ]
        if inconnus:
            raise PlanImpossible(
                f"fusion {', '.join(groupe)} : champ(s) absent(s) des arbres "
                f"({', '.join(inconnus)})."
            )
        bloques = [c for c in groupe if c in ecartes]
        if bloques:
            raise PlanImpossible(
                f"fusion {', '.join(groupe)} : champ(s) exclu(s) ou a polarite "
                f"inversee ({', '.join(bloques)})."
            )
        jeux = {o.valeurs for c in groupe for o in par_champ[c]}
        if len(jeux) > 1:
            raise PlanImpossible(
                f"fusion {', '.join(groupe)} : les reponses possibles different "
                f"({' / '.join(sorted(', '.join(sorted(j)) for j in jeux))})."
            )
        for c in groupe[1:]:
            uf.union(groupe[0], c)

    composantes: dict[str, list[str]] = defaultdict(list)
    for champ in par_champ:
        if champ in ecartes:
            continue
        composantes[uf.find(champ)].append(champ)

    forces = list(canoniques_forces)
    for membres in composantes.values():
        if len(membres) < 2:
            continue
        compte = {c: len(par_champ[c]) for c in membres}
        forces_ici = [c for c in forces if c in membres]
        if len(forces_ici) > 1:
            raise PlanImpossible(
                f"plusieurs canoniques forces dans le meme groupe : "
                f"{', '.join(forces_ici)}."
            )
        if forces_ici:
            canonique = forces_ici[0]
        else:
            canonique = sorted(
                membres, key=lambda c: (-compte[c], -score_descriptif(c), c)
            )[0]
        plan.groupes.append(
            GroupeNormalisation(
                canonique=canonique,
                champs=sorted(membres, key=lambda c: (c != canonique, c)),
                occurrences=[o for c in membres for o in par_champ[c]],
                compte_par_champ=compte,
            )
        )
    plan.groupes.sort(key=lambda g: g.canonique)

    for c in forces:
        if c not in par_champ:
            raise PlanImpossible(f"canonique force {c!r} absent des arbres.")

    # Candidats a une fusion humaine : textes proches, memes reponses, pas
    # deja dans le meme groupe.
    groupe_de = {c: g.canonique for g in plan.groupes for c in g.champs}
    representants: dict[str, OccurrenceQC] = {}
    for champ, occs in par_champ.items():
        if champ not in ecartes:
            texte = Counter(o.texte_norm for o in occs).most_common(1)[0][0]
            representants[champ] = next(o for o in occs if o.texte_norm == texte)
    champs = sorted(representants)
    for i, a in enumerate(champs):
        for b in champs[i + 1 :]:  # noqa: E203
            if groupe_de.get(a, a) == groupe_de.get(b, b):
                continue
            oa, ob = representants[a], representants[b]
            if oa.valeurs != ob.valeurs:
                continue
            score = SequenceMatcher(None, oa.texte_norm, ob.texte_norm).ratio()
            if score >= seuil_proches:
                plan.proches.append((a, b, round(score, 2)))
    plan.proches.sort(key=lambda p: -p[2])
    return plan


# ─── Reecriture d'un arbre ──────────────────────────────────────────────────


class RenommageImpossible(ValueError):
    """Une reference au champ ne peut pas etre reecrite sans risque."""


@dataclass(frozen=True)
class Modification:
    nature: str  # champ | expression | remap_contexte | inputs_requis
    lieu: str  # id du noeud / de la regle concerne
    avant: str
    apres: str


def renommer_dans_expression(expression: str, mapping: dict[str, str]) -> str:
    """Renomme les variables d'une expression de catalogue parametre.

    Passe par l'AST : seuls les noms de variables sont touches, jamais une
    chaine litterale qui contiendrait le meme mot. La mise en forme est
    conservee (remplacement aux positions exactes)."""
    try:
        arbre = ast.parse(expression, mode="eval")
    except SyntaxError:
        for ancien in mapping:
            if re.search(rf"\b{re.escape(ancien)}\b", expression):
                raise RenommageImpossible(
                    f"expression non analysable qui mentionne {ancien!r} : "
                    f"{expression!r}"
                )
        return expression
    noms = [n for n in ast.walk(arbre) if isinstance(n, ast.Name) and n.id in mapping]
    if not noms:
        return expression
    # Les positions de l'AST sont en octets UTF-8 (litteraux accentues).
    lignes = [ligne.encode("utf-8") for ligne in expression.splitlines(True)]
    for n in sorted(noms, key=lambda n: (n.lineno, n.col_offset), reverse=True):
        i = n.lineno - 1
        b = lignes[i]
        debut, fin = n.col_offset, n.end_col_offset
        lignes[i] = b[:debut] + mapping[n.id].encode() + b[fin:]
    return b"".join(lignes).decode("utf-8")


def _renommer_regle(regle: dict, mapping: dict, modifs: list[Modification]) -> None:
    inputs = regle.get("inputs_requis")
    if not isinstance(inputs, list):
        return
    for i, item in enumerate(inputs):
        if isinstance(item, str) and item in mapping:
            inputs[i] = mapping[item]
            modifs.append(
                Modification("inputs_requis", str(regle.get("id", "")), item, inputs[i])
            )


def renommer_champs(contenu: dict, mapping: dict[str, str]) -> list[Modification]:
    """Applique `mapping` (ancien champ -> nouveau) a un arbre, EN PLACE.

    Reecrit : le `champ` des noeuds, les variables des expressions de
    catalogue parametre, les cles de `remap_contexte`, et les `inputs_requis`
    historiques (forme chaine). Leve RenommageImpossible si une reference ne
    peut pas etre reecrite sans risque ; l'arbre n'est alors PAS modifie (on
    travaille sur une copie de controle d'abord)."""
    if not mapping:
        return []
    essai = copy.deepcopy(contenu)
    modifs = _renommer(essai, mapping)
    # Aucune exception : on rejoue sur l'original.
    _renommer(contenu, mapping)
    return modifs


def _renommer(contenu: dict, mapping: dict[str, str]) -> list[Modification]:
    modifs: list[Modification] = []
    for noeud in iter_noeuds(contenu):
        nid = str(noeud.get("id", ""))
        champ = noeud.get("champ")
        if isinstance(champ, str) and champ in mapping:
            noeud["champ"] = mapping[champ]
            modifs.append(Modification("champ", nid, champ, noeud["champ"]))
        for branche in noeud.get("branches") or []:
            if not isinstance(branche, dict):
                continue
            expr = branche.get("expression")
            if isinstance(expr, str):
                nouvelle = renommer_dans_expression(expr, mapping)
                if nouvelle != expr:
                    branche["expression"] = nouvelle
                    modifs.append(Modification("expression", nid, expr, nouvelle))
            remap = branche.get("remap_contexte")
            if isinstance(remap, dict) and any(k in mapping for k in remap):
                nouveau: dict = {}
                for k, v in remap.items():
                    cible = mapping.get(k, k)
                    if cible in nouveau and nouveau[cible] != v:
                        raise RenommageImpossible(
                            f"remap_contexte du noeud {nid!r} : {k!r} et "
                            f"{cible!r} recoivent des valeurs differentes."
                        )
                    nouveau[cible] = v
                avant = ", ".join(sorted(map(str, remap)))
                remap.clear()
                remap.update(nouveau)
                modifs.append(
                    Modification(
                        "remap_contexte", nid, avant, ", ".join(sorted(map(str, remap)))
                    )
                )
            if isinstance(branche.get("regle"), dict):
                _renommer_regle(branche["regle"], mapping, modifs)
    for cle in ("plafonnements", "regles_partagees"):
        for entree in (contenu or {}).get(cle) or []:
            if isinstance(entree, dict) and isinstance(entree.get("regle"), dict):
                _renommer_regle(entree["regle"], mapping, modifs)
    return modifs
