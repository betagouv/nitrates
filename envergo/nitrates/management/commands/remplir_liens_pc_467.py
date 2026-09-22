"""Remplit les « cliquez ici :  ) » vides des blocs riches PC (#467).

Les PC Grand Est renvoient vers le dispositif de suivi des reliquats
(annexe 2 du PAR GE) et vers la définition des sols à faible disponibilité
en azote (annexe 3 du PAR GE). Les annexes sont servies en statique et
référencées via la table LienReference (liens syndiqués) : les blocs
portent des segments {texte, lien_ref} résolus au rendu, l'URL réelle se
pilote en DB.

La commande :
  1. crée (get_or_create) les 2 LienReference annexe 2 / annexe 3 ;
  2. remplace le texte plat « (pour connaître …, cliquez ici :  ) » par des
     segments {texte, lien_ref} ;
  3. convertit les segments {lien: <URL annexe>} posés par une exécution
     d'une version antérieure de cette commande en {lien_ref}.

Idempotent : motif absent + liens déjà syndiqués -> aucune écriture.

Usage :
    python manage.py remplir_liens_pc_467
    python manage.py remplir_liens_pc_467 --dry-run
"""

import re

from django.core.management.base import BaseCommand

REF_ANNEXE_2 = "par-ge-annexe2-reliquats"
REF_ANNEXE_3 = "par-ge-annexe3-sols"

_LIENS = {
    REF_ANNEXE_2: {
        "url": "/static/nitrates/documents/par-ge-annexe2-modalites-reliquats.pdf",
        "libelle": "consultez l'annexe 2 du PAR Grand Est (PDF)",
        "description": (
            "Annexe 2 du PAR Grand Est : dispositif de surveillance des "
            "reliquats azotés (protocole, îlots représentatifs, sols "
            "impropres, bilan azoté post-récolte). Référencée par les PC "
            "1-4 et 10 Grand Est (#467)."
        ),
    },
    REF_ANNEXE_3: {
        "url": "/static/nitrates/documents/par-ge-annexe3-sols-faible-dispo-azote.pdf",
        "libelle": "consultez l'annexe 3 du PAR Grand Est (PDF)",
        "description": (
            "Annexe 3 du PAR Grand Est : définition des sols à faible "
            "disponibilité en azote. Référencée par la PC 11 Grand Est "
            "(#467)."
        ),
    },
}

# (motif de la parenthèse à lien vide, identifiant LienReference, préfixe
# conservé avant le lien)
_MOTIFS = [
    (
        re.compile(
            r"\(pour connaître le dispositif de suivi à mettre en place"
            r" en Grand Est,? cliquez ici :?\s*\)"
        ),
        REF_ANNEXE_2,
        "pour connaître le dispositif de suivi à mettre en place en Grand Est, ",
    ),
    (
        re.compile(r"\(pour connaître les sols concernés,? cliquez ici :?\s*\)"),
        REF_ANNEXE_3,
        "pour connaître les sols concernés, ",
    ),
]

# URL brute -> identifiant, pour convertir les segments {lien} posés par la
# version pré-LienReference de cette commande.
_URLS_VERS_REF = {infos["url"]: ident for ident, infos in _LIENS.items()}


def _transformer_texte(texte):
    """string -> liste de segments si un motif est trouvé, sinon None."""
    for motif, ref, prefixe in _MOTIFS:
        m = motif.search(texte)
        if not m:
            continue
        segments = []
        avant = texte[: m.start()] + "(" + prefixe
        fin = m.end()
        apres = ")" + texte[fin:]
        if avant:
            segments.append({"texte": avant})
        segments.append({"texte": _LIENS[ref]["libelle"], "lien_ref": ref})
        segments.append({"texte": apres})
        return segments
    return None


def _walk(obj):
    """Parcourt le JSON blocs : transforme les `texte` string porteurs du
    motif et syndique les segments {lien: <URL annexe>}. Retourne True si au
    moins une transformation a eu lieu."""
    touche = False
    if isinstance(obj, dict):
        texte = obj.get("texte")
        if isinstance(texte, str):
            segments = _transformer_texte(texte)
            if segments:
                obj["texte"] = segments
                touche = True
        ref = _URLS_VERS_REF.get(obj.get("lien"))
        if ref:
            del obj["lien"]
            obj["lien_ref"] = ref
            touche = True
        for valeur in obj.values():
            touche = _walk(valeur) or touche
    elif isinstance(obj, list):
        for element in obj:
            touche = _walk(element) or touche
    return touche


class Command(BaseCommand):
    help = "Remplit les liens annexes PAR GE dans les blocs riches PC (#467)"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        from envergo.nitrates.models import CodePrescription, LienReference

        dry_run = options.get("dry_run", False)
        prefix = "[dry-run] " if dry_run else ""

        for ident, infos in _LIENS.items():
            if dry_run:
                if not LienReference.objects.filter(identifiant=ident).exists():
                    self.stdout.write(f"{prefix}LienReference {ident} : à créer")
                continue
            _, cree = LienReference.objects.get_or_create(
                identifiant=ident, defaults=infos
            )
            if cree:
                self.stdout.write(f"LienReference {ident} : créé")

        modifies = []
        for cp in CodePrescription.objects.exclude(blocs__isnull=True).order_by(
            "identifiant"
        ):
            if not cp.blocs:
                continue
            if _walk(cp.blocs):
                modifies.append(cp.identifiant)
                if not dry_run:
                    cp.save(update_fields=["blocs"])
        for ident in modifies:
            self.stdout.write(f"{prefix}{ident} : lien(s) syndiqué(s)")
        self.stdout.write(
            self.style.SUCCESS(f"{prefix}{len(modifies)} PC modifiée(s).")
        )
