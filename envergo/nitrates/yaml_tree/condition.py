"""Mini-DSL pour le champ `condition` des periodes de type calculatrice.

Format MVP-2 (cf. spec_extension_grammaire_condition) :

    <input_id> <operateur> <date_litterale>

Exemples :
    date_destruction_couvert < 05/12
    date_semis_couvert >= 01/09
    date_destruction_couvert == 31/12

Le parser produit un objet `Condition(input_id, op, date_litterale)`. La
validation grammaticale (input_id present dans inputs_requis et de
type=date, date valide JJ/MM) est faite par `validate_condition`.

L'evaluation a runtime (savoir si la condition est vraie pour un
contexte utilisateur donne) est faite cote front (JS) dans le
composant calendrier dynamique : le backend ne resout jamais les
inputs utilisateur, donc evaluer la condition ici n'a aucun usage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

OPERATEURS = ("<=", ">=", "==", "!=", "<", ">")

# Ordre des operateurs : 2 caracteres d'abord pour ne pas matcher `<` dans `<=`.
_CONDITION_RE = re.compile(
    r"^\s*"
    r"(?P<input_id>[a-z][a-z0-9_]*)"
    r"\s*"
    r"(?P<op><=|>=|==|!=|<|>)"
    r"\s*"
    r"(?P<date>\d{2}/\d{2})"
    r"\s*$"
)

DATE_FIXE_RE = re.compile(r"^\d{2}/\d{2}$")


@dataclass(frozen=True)
class Condition:
    """Forme parsee d'une condition. Normalisee : un seul espace autour
    de l'operateur a la serialisation."""

    input_id: str
    op: str
    date_litterale: str

    def normalise(self) -> str:
        return f"{self.input_id} {self.op} {self.date_litterale}"


class ConditionParseError(ValueError):
    """Levee quand une chaine ne respecte pas la grammaire condition."""


def parse_condition(raw: str) -> Condition:
    """Parse une chaine condition. Leve ConditionParseError si invalide
    structurellement. Ne verifie PAS que l'input_id existe ni que la
    date est valide -- ces checks sont semantiques (cf. validate_condition).
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ConditionParseError("condition vide")
    m = _CONDITION_RE.match(raw)
    if not m:
        raise ConditionParseError(
            f"condition {raw!r} ne respecte pas le format "
            "'<input_id> <op> <JJ/MM>' (operateurs : "
            f"{', '.join(OPERATEURS)})"
        )
    return Condition(
        input_id=m.group("input_id"),
        op=m.group("op"),
        date_litterale=m.group("date"),
    )


def _is_valid_date(s: str) -> bool:
    try:
        jour, mois = s.split("/")
        j, m = int(jour), int(mois)
        return 1 <= j <= 31 and 1 <= m <= 12
    except (ValueError, AttributeError):
        return False


def validate_condition(
    raw: str, inputs_requis: list[dict]
) -> tuple[Condition | None, str | None]:
    """Parse + valide semantiquement.

    Retourne (condition, None) si valide, (None, message) si invalide.

    inputs_requis : la liste des inputs de la regle calculatrice
    courante (forme dict {id, label, type, ...}).

    Checks :
      1. Structure (cf. parse_condition).
      2. L'input_id reference existe dans inputs_requis.
      3. L'input reference est de type=date (les autres types n'ont pas
         de sens pour une comparaison avec une date litterale).
      4. La date litterale est un JJ/MM valide.
    """
    try:
        cond = parse_condition(raw)
    except ConditionParseError as exc:
        return None, str(exc)

    input_dict = {
        i.get("id"): i
        for i in (inputs_requis or [])
        if isinstance(i, dict) and i.get("id")
    }
    if cond.input_id not in input_dict:
        return (
            None,
            f"condition {raw!r} : input_id {cond.input_id!r} absent de "
            f"inputs_requis",
        )
    if input_dict[cond.input_id].get("type") != "date":
        return (
            None,
            f"condition {raw!r} : input_id {cond.input_id!r} doit etre "
            f"de type 'date' (les autres types ne sont pas comparables a "
            f"une date litterale)",
        )
    if not _is_valid_date(cond.date_litterale):
        return (
            None,
            f"condition {raw!r} : date {cond.date_litterale!r} invalide "
            f"(jour/mois hors borne)",
        )
    return cond, None
