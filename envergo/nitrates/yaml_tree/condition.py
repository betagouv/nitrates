"""Mini-DSL pour le champ `condition` des periodes de type calculatrice.

Format (cf. spec_extension_grammaire_condition) :

    <comparaison> [&& <comparaison>]*

ou une `comparaison` est :

    <terme> <operateur> <terme>

et un `terme` est, EXACTEMENT comme une borne `du`/`au` de periode :
    - une date litterale JJ/MM            (ex 15/12)
    - un event (input_id de type date)    (ex date_semis_couvert)
    - un event +/- offset                 (ex date_semis_couvert+4semaines,
                                               date_destruction_couvert-20jours)

`&&` joint plusieurs comparaisons en conjonction (ET) : la condition est vraie
si TOUTES les comparaisons le sont. Pas de `||` (OU) ni de parentheses : pour
un OU, dupliquer la periode avec chacune sa condition.

Exemples valides :
    date_destruction_couvert < 05/12
    date_semis_couvert+4semaines > 15/12
    15/12 <= date_destruction_couvert
    date_semis_couvert > 15/09 && date_semis_couvert < 15/11

Le parser produit un `ConditionExpr` = liste de `Condition(gauche, op, droite)`
(chacune une comparaison), jointes en ET. La validation grammaticale (events
presents dans inputs_requis et de type=date, dates valides, unites connues) est
faite par `validate_condition`.

L'evaluation a runtime (savoir si la condition est vraie pour un contexte
utilisateur donne) est faite cote front (JS) dans le composant calendrier
dynamique : le backend ne resout jamais les inputs utilisateur, donc evaluer
la condition ici n'a aucun usage. Le JS reutilise la meme grammaire de terme
que `parseBorne` -- backend et front DOIVENT rester synchronises.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

OPERATEURS = ("<=", ">=", "==", "!=", "<", ">")
UNITES = ("jours", "semaines", "mois")
# Separateur de conjonction (ET). Une condition = 1+ comparaisons jointes par
# `&&`. Pas de OU ni de parentheses (cf. docstring module).
ET = "&&"

# Un terme : date JJ/MM, ou event, ou event +/- N unite. Meme grammaire que
# la borne du/au d'une periode (cf. BORNE_RE cote JS).
_TERME = r"\d{2}/\d{2}|[a-z][a-z0-9_]*(?:[+-]\d+(?:jours|semaines|mois))?"

# Condition = terme op terme. L'operateur 2-char d'abord (sinon `<` mange `<=`).
_CONDITION_RE = re.compile(
    r"^\s*"
    r"(?P<gauche>" + _TERME + r")"
    r"\s*"
    r"(?P<op><=|>=|==|!=|<|>)"
    r"\s*"
    r"(?P<droite>" + _TERME + r")"
    r"\s*$"
)

DATE_FIXE_RE = re.compile(r"^\d{2}/\d{2}$")
_EVENT_OFFSET_RE = re.compile(
    r"^(?P<event>[a-z][a-z0-9_]*)"
    r"(?:(?P<sign>[+-])(?P<n>\d+)(?P<unit>jours|semaines|mois))?$"
)


@dataclass(frozen=True)
class Terme:
    """Un membre de condition. Soit une date fixe (`date` rempli, `event`
    None), soit un event eventuellement decale (`event` rempli, `date` None).
    """

    raw: str
    date: str | None = None  # JJ/MM si terme = date litterale
    event: str | None = None  # input_id si terme = event
    sign: str | None = None  # '+' / '-' si offset
    n: int | None = None  # quantite d'offset
    unit: str | None = None  # 'jours' | 'semaines' | 'mois'

    @property
    def is_date(self) -> bool:
        return self.date is not None

    @property
    def is_event(self) -> bool:
        return self.event is not None


@dataclass(frozen=True)
class Condition:
    """Forme parsee d'une condition : `gauche op droite`.

    Retrocompat : l'ancien code accedait a `.input_id` et `.date_litterale`
    sur des conditions `event < date`. On expose des proprietes de compat
    quand la forme s'y prete, mais le nouveau code doit utiliser
    `gauche`/`op`/`droite`.
    """

    gauche: Terme
    op: str
    droite: Terme

    def normalise(self) -> str:
        return f"{self.gauche.raw} {self.op} {self.droite.raw}"

    # ── Compat ascendante (ancienne forme event<date) ────────────────────
    @property
    def input_id(self) -> str | None:
        return self.gauche.event

    @property
    def date_litterale(self) -> str | None:
        return self.droite.date


@dataclass(frozen=True)
class ConditionExpr:
    """Une condition complete : 1+ comparaisons jointes en ET (`&&`).

    `comparaisons` contient au moins un element. Quand il n'y en a qu'un, on
    expose des proprietes de compat (`gauche`/`op`/`droite`/`input_id`/
    `date_litterale`) qui delèguent a cette unique comparaison, pour que le
    code et les tests ecrits avant l'ajout du `&&` continuent de marcher.
    """

    comparaisons: tuple[Condition, ...]

    def normalise(self) -> str:
        return f" {ET} ".join(c.normalise() for c in self.comparaisons)

    # ── Compat ascendante (condition = 1 seule comparaison) ───────────────
    @property
    def gauche(self) -> Terme:
        return self.comparaisons[0].gauche

    @property
    def op(self) -> str:
        return self.comparaisons[0].op

    @property
    def droite(self) -> Terme:
        return self.comparaisons[0].droite

    @property
    def input_id(self) -> str | None:
        return self.comparaisons[0].input_id

    @property
    def date_litterale(self) -> str | None:
        return self.comparaisons[0].date_litterale


class ConditionParseError(ValueError):
    """Levee quand une chaine ne respecte pas la grammaire condition."""


def _parse_terme(raw: str) -> Terme:
    raw = raw.strip()
    if DATE_FIXE_RE.match(raw):
        return Terme(raw=raw, date=raw)
    m = _EVENT_OFFSET_RE.match(raw)
    if not m:
        raise ConditionParseError(f"terme {raw!r} invalide")
    return Terme(
        raw=raw,
        event=m.group("event"),
        sign=m.group("sign"),
        n=int(m.group("n")) if m.group("n") else None,
        unit=m.group("unit"),
    )


def parse_condition(raw: str) -> Condition:
    """Parse une chaine condition. Leve ConditionParseError si invalide
    structurellement. Ne verifie PAS que les events existent ni que les
    dates sont valides -- ces checks sont semantiques (cf. validate_condition).
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ConditionParseError("condition vide")
    m = _CONDITION_RE.match(raw)
    if not m:
        raise ConditionParseError(
            f"condition {raw!r} ne respecte pas le format "
            "'<terme> <op> <terme>' ou un terme est JJ/MM, un event, ou "
            "event±Nunite (ex date_semis_couvert+4semaines > 15/12) "
            f"(operateurs : {', '.join(OPERATEURS)} ; "
            f"unites : {', '.join(UNITES)})"
        )
    return Condition(
        gauche=_parse_terme(m.group("gauche")),
        op=m.group("op"),
        droite=_parse_terme(m.group("droite")),
    )


def parse_condition_expr(raw: str) -> ConditionExpr:
    """Parse une condition complete : 1+ comparaisons jointes par `&&`.

    Leve ConditionParseError si la chaine est vide, si une part autour d'un
    `&&` est vide (ex `a && `, `&& b`, `a && && b`), ou si une comparaison ne
    respecte pas la grammaire `<terme> <op> <terme>`. Ne verifie PAS la
    semantique (events existants, dates valides) -- cf. validate_condition.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ConditionParseError("condition vide")
    parts = raw.split(ET)
    comparaisons = []
    for part in parts:
        if not part.strip():
            raise ConditionParseError(
                f"condition {raw!r} : comparaison vide autour d'un {ET!r} "
                f"(format attendu : 'cmp {ET} cmp', chaque cmp = "
                "'<terme> <op> <terme>')"
            )
        comparaisons.append(parse_condition(part))
    return ConditionExpr(comparaisons=tuple(comparaisons))


def _is_valid_date(s: str) -> bool:
    try:
        jour, mois = s.split("/")
        j, m = int(jour), int(mois)
        return 1 <= j <= 31 and 1 <= m <= 12
    except (ValueError, AttributeError):
        return False


def _valider_terme(terme: Terme, raw: str, input_dict: dict) -> str | None:
    """Valide un terme. Retourne un message d'erreur, ou None si OK."""
    if terme.is_date:
        if not _is_valid_date(terme.date):
            return (
                f"condition {raw!r} : date {terme.date!r} invalide "
                f"(jour/mois hors borne)"
            )
        return None
    # terme = event
    if terme.event not in input_dict:
        return (
            f"condition {raw!r} : input_id {terme.event!r} absent de " f"inputs_requis"
        )
    if input_dict[terme.event].get("type") != "date":
        return (
            f"condition {raw!r} : input_id {terme.event!r} doit etre de "
            f"type 'date' (les autres types ne sont pas comparables a une date)"
        )
    if terme.unit is not None and terme.unit not in UNITES:
        return (
            f"condition {raw!r} : unite {terme.unit!r} inconnue "
            f"(attendu : {', '.join(UNITES)})"
        )
    return None


def validate_condition(
    raw: str, inputs_requis: list[dict]
) -> tuple[ConditionExpr | None, str | None]:
    """Parse + valide semantiquement une condition (1+ comparaisons en ET).

    Retourne (expr, None) si valide, (None, message) si invalide.

    inputs_requis : la liste des inputs de la regle calculatrice courante
    (forme dict {id, label, type, ...}).

    Checks (sur CHAQUE comparaison jointe par `&&`) :
      1. Structure (cf. parse_condition_expr / parse_condition).
      2. Chaque terme : si event, present dans inputs_requis et de type=date,
         unite connue ; si date, JJ/MM valide.
      3. Au moins un des deux termes doit etre un event (comparer deux dates
         fixes serait une comparaison constante, sans interet et probablement
         une erreur de saisie). Verifie par comparaison : `a && 15/12 < 31/01`
         est rejete a cause de la part constante.
    """
    try:
        expr = parse_condition_expr(raw)
    except ConditionParseError as exc:
        return None, str(exc)

    input_dict = {
        i.get("id"): i
        for i in (inputs_requis or [])
        if isinstance(i, dict) and i.get("id")
    }

    for cmp in expr.comparaisons:
        for terme in (cmp.gauche, cmp.droite):
            err = _valider_terme(terme, raw, input_dict)
            if err:
                return None, err

        if not (cmp.gauche.is_event or cmp.droite.is_event):
            return (
                None,
                f"condition {raw!r} : la comparaison {cmp.normalise()!r} doit "
                f"contenir au moins un event (comparer deux dates fixes est "
                f"une condition constante)",
            )

    return expr, None
