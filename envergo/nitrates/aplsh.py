"""Moteur APLSH : parsing des tableaux régionaux + calcul des doses.

APLSH = azote potentiellement libéré jusqu'en sortie d'hiver (15 janvier) :
somme de l'azote minéral et de l'azote organique minéralisable d'un
fertilisant organique entre sa date d'apport et la sortie d'hiver. Le 7e
PAN plafonne l'APLSH cumulé des apports sur couverts d'interculture et
prairies (70 kg N/ha en règle générale, mesure 1 « plafonnement »).

Le calcul est identique dans toutes les régions :

    APLSH (kg N/ha) = dose (t ou m³/ha) × N total (kg/t ou m³) × p
    dose max        = plafond / (N total × p)

Seules les DONNÉES sont régionales (référentiels GREN) : liste des
produits, teneurs N par défaut, coefficients « p » été/automne, bornes de
saison. Elles vivent dans `ReferentielAPLSH` (models_aplsh.py) sous forme
de tableaux texte pipe-séparés, parsés et validés ici contre la
nomenclature `Fertilisant` (jamais de produit orphelin, cf. discussion
POC : la liste canonique des fertilisants reste la nôtre, les régions n'y
attachent que des valeurs, au besoin par `variante`).
"""

from dataclasses import dataclass, field
from datetime import date

# ─── Format des tableaux texte ────────────────────────────────────────────────
#
# Tableau produits : 1 ligne par produit régional, colonnes séparées par `|`.
#   fertilisant | variante | unite | n_total | p_ete | p_automne
# - fertilisant : identifiant d'un Fertilisant existant (FK logique, validée)
# - variante    : libellé libre quand la région subdivise plus fin que notre
#                 nomenclature (ex "Bovins — dépôt au champ"), vide si 1-1
# - unite       : "t" (produit solide) ou "m3" (liquide), vide si inconnu
# - n_total     : kg N par unité, vide si la région ne le fournit pas
#                 (la calculette le demandera à l'utilisateur)
# - p_ete / p_automne : coefficients 0..1 (accepte virgule décimale et %)
#
# Tableau générique (produits hors liste, caractérisés par analyse — GE) :
#   cn_max | nmin_ntot_max | p_ete | p_automne
# Lignes triées par (cn_max, nmin_ntot_max) croissants ; cn_max / nmin_ntot_max
# vides = pas de borne supérieure (dernière tranche). La résolution prend la
# première ligne dont les deux bornes couvrent la valeur.

COLONNES_PRODUITS = [
    "fertilisant",
    "variante",
    "unite",
    "n_total",
    "p_ete",
    "p_automne",
]
UNITES = {"t", "m3", ""}
COLONNES_GENERIQUE = ["cn_max", "nmin_ntot_max", "p_ete", "p_automne"]


class ErreurTableauAPLSH(ValueError):
    """Erreur de parsing d'un tableau APLSH, avec numéro de ligne."""


def _nombre(brut, ligne_no, colonne, pourcent_ok=True):
    """Parse un nombre acceptant virgule décimale et suffixe %."""
    txt = brut.strip().replace(",", ".")
    if not txt:
        return None
    facteur = 1.0
    if txt.endswith("%"):
        if not pourcent_ok:
            raise ErreurTableauAPLSH(
                f"Ligne {ligne_no} : « % » interdit dans la colonne {colonne}."
            )
        txt = txt[:-1].strip()
        facteur = 0.01
    try:
        # round : évite les artefacts binaires du type 70% → 0.7000000000000001
        return round(float(txt) * facteur, 6)
    except ValueError:
        raise ErreurTableauAPLSH(
            f"Ligne {ligne_no} : valeur numérique invalide « {brut.strip()} » "
            f"(colonne {colonne})."
        )


def _lignes(texte):
    """Découpe le texte en lignes utiles (saute vides, commentaires, entête)."""
    lignes = []
    for no, brute in enumerate(texte.splitlines(), start=1):
        ligne = brute.strip()
        if not ligne or ligne.startswith("#"):
            continue
        cellules = [c.strip() for c in ligne.split("|")]
        # Entête optionnelle recopiant les noms de colonnes
        if no <= 3 and cellules[0].lower() in ("fertilisant", "cn_max"):
            continue
        lignes.append((no, cellules))
    return lignes


def _coefficient(cellules, no, colonne):
    p = _nombre(cellules, no, colonne)
    if p is None:
        raise ErreurTableauAPLSH(f"Ligne {no} : colonne {colonne} obligatoire.")
    if not (0 <= p <= 1):
        raise ErreurTableauAPLSH(
            f"Ligne {no} : coefficient {colonne}={p:g} hors de [0 ; 1] "
            "(saisir 0,40 ou 40%)."
        )
    return p


def parser_tableau_produits(texte, identifiants_fertilisants):
    """Parse et valide le tableau produits.

    `identifiants_fertilisants` : ensemble des identifiants Fertilisant
    autorisés (injecté pour rester testable sans DB). Retourne une liste de
    dicts sérialisables JSON. Lève ErreurTableauAPLSH sinon.
    """
    resultat = []
    vus = set()
    for no, cellules in _lignes(texte):
        if len(cellules) != len(COLONNES_PRODUITS):
            raise ErreurTableauAPLSH(
                f"Ligne {no} : {len(cellules)} colonne(s) au lieu de "
                f"{len(COLONNES_PRODUITS)} ({' | '.join(COLONNES_PRODUITS)})."
            )
        fertilisant, variante, unite, n_total, p_ete, p_automne = cellules
        if unite not in UNITES:
            raise ErreurTableauAPLSH(
                f"Ligne {no} : unité « {unite} » invalide (t, m3 ou vide)."
            )
        if not fertilisant:
            raise ErreurTableauAPLSH(f"Ligne {no} : identifiant fertilisant vide.")
        if fertilisant not in identifiants_fertilisants:
            raise ErreurTableauAPLSH(
                f"Ligne {no} : fertilisant inconnu « {fertilisant} » — doit "
                "être l'identifiant d'un Fertilisant existant (référentiel "
                "nitrates). Créer d'abord le fertilisant, ou corriger la faute."
            )
        cle = (fertilisant, variante)
        if cle in vus:
            raise ErreurTableauAPLSH(
                f"Ligne {no} : doublon fertilisant/variante "
                f"« {fertilisant} / {variante or '—'} »."
            )
        vus.add(cle)
        n = _nombre(n_total, no, "n_total", pourcent_ok=False)
        if n is not None and n <= 0:
            raise ErreurTableauAPLSH(f"Ligne {no} : n_total doit être > 0.")
        resultat.append(
            {
                "fertilisant": fertilisant,
                "variante": variante,
                "unite": unite,
                "n_total": n,
                "p_ete": _coefficient(p_ete, no, "p_ete"),
                "p_automne": _coefficient(p_automne, no, "p_automne"),
            }
        )
    if not resultat:
        raise ErreurTableauAPLSH("Tableau produits vide.")
    return resultat


def parser_tableau_generique(texte):
    """Parse la grille générique C/N × Nmin/Ntot (optionnelle)."""
    resultat = []
    for no, cellules in _lignes(texte):
        if len(cellules) != len(COLONNES_GENERIQUE):
            raise ErreurTableauAPLSH(
                f"Ligne {no} : {len(cellules)} colonne(s) au lieu de "
                f"{len(COLONNES_GENERIQUE)} ({' | '.join(COLONNES_GENERIQUE)})."
            )
        cn_max, ratio_max, p_ete, p_automne = cellules
        resultat.append(
            {
                "cn_max": _nombre(cn_max, no, "cn_max", pourcent_ok=False),
                "nmin_ntot_max": _nombre(ratio_max, no, "nmin_ntot_max"),
                "p_ete": _coefficient(p_ete, no, "p_ete"),
                "p_automne": _coefficient(p_automne, no, "p_automne"),
            }
        )
    return resultat


def resoudre_p_generique(grille, cn, nmin_ntot):
    """Trouve le p dans la grille générique pour un produit caractérisé.

    La grille est en tranches « bornes max » croissantes ; on prend la
    première ligne dont cn_max ET nmin_ntot_max couvrent la valeur (borne
    vide = infini). Retourne la ligne, ou None si rien ne couvre.
    """
    candidates = sorted(
        grille,
        key=lambda ligne: (
            ligne["cn_max"] if ligne["cn_max"] is not None else float("inf"),
            (
                ligne["nmin_ntot_max"]
                if ligne["nmin_ntot_max"] is not None
                else float("inf")
            ),
        ),
    )
    for ligne in candidates:
        cn_ok = ligne["cn_max"] is None or cn <= ligne["cn_max"]
        ratio_ok = ligne["nmin_ntot_max"] is None or nmin_ntot <= ligne["nmin_ntot_max"]
        if cn_ok and ratio_ok:
            return ligne
    return None


# ─── Saisons et calcul ────────────────────────────────────────────────────────


def parser_jour_mois(texte):
    """Parse une borne JJ/MM en tuple (mois, jour)."""
    try:
        jour, mois = (int(x) for x in texte.strip().split("/"))
        date(2001, mois, jour)  # valide (année quelconque non bissextile)
    except (ValueError, TypeError):
        raise ErreurTableauAPLSH(f"Borne de saison invalide « {texte} » (JJ/MM).")
    return (mois, jour)


def saison_apport(date_apport, fin_ete="15/09"):
    """'ete' ou 'automne' selon la date d'apport et la borne régionale.

    La fenêtre APLSH court de la récolte du précédent au 15 janvier. Les
    apports de janvier (jusqu'au 15/01) relèvent de la campagne entamée à
    l'été précédent → 'automne'.
    """
    mois, jour = parser_jour_mois(fin_ete)
    if (date_apport.month, date_apport.day) <= (mois, jour) and date_apport.month >= 2:
        return "ete"
    return "automne"


# Plafond de la directive nitrates (annexe III) repris par le PAN : 170 kg
# d'azote issu des effluents d'ÉLEVAGE par hectare et par an (moyenne sur la
# surface agricole utile de l'exploitation). Garde-fou de la calculette :
# les produits pauvres à coefficient APLSH faible (fumiers compacts…)
# atteignent ce plafond bien avant le plafond APLSH.
PLAFOND_EFFLUENTS_ELEVAGE_KG_N_HA = 170


@dataclass
class ResultatAPLSH:
    """Résultat de calcul pour un apport donné."""

    plafond: float
    n_total: float
    p: float
    saison: str
    plafond_azote_total: float | None = None
    dose_max: float = field(init=False)
    dose: float | None = None
    dose_max_aplsh: float = field(init=False, default=0.0)
    limite: str = field(init=False, default="aplsh")
    azote_total: float | None = field(init=False, default=None)
    aplsh: float | None = field(init=False, default=None)
    conforme: bool | None = field(init=False, default=None)
    marge: float | None = field(init=False, default=None)
    depassement_pct: float | None = field(init=False, default=None)

    def __post_init__(self):
        import math

        aplsh_par_unite = self.n_total * self.p
        self.dose_max_aplsh = self.plafond / aplsh_par_unite if aplsh_par_unite else 0.0
        self.limite = "aplsh"
        self.dose_max = self.dose_max_aplsh
        if self.plafond_azote_total and self.n_total:
            dose_max_totale = self.plafond_azote_total / self.n_total
            if dose_max_totale < self.dose_max:
                self.dose_max = dose_max_totale
                self.limite = "azote_total"
        # Affichage TRONQUÉ au dixième inférieur : la valeur montrée à
        # l'utilisateur doit toujours être conforme quand il la ressaisit
        # (4,74 affiché « 4,7 » et non arrondi à « 4,8 » qui dépasserait).
        self.dose_max_affichee = math.floor(self.dose_max * 10) / 10
        if self.dose is not None:
            self.aplsh = self.dose * aplsh_par_unite
            self.azote_total = self.dose * self.n_total
            # Tolérance d'un demi-dixième sur la DOSE (granularité de
            # l'affichage) : ressaisir la dose max affichée arrondie ne doit
            # jamais basculer le verdict en dépassement.
            self.conforme = self.dose <= self.dose_max + 0.05 + 1e-9
            self.marge = max(self.dose_max - self.dose, 0.0)
            self.depassement_pct = max(
                100 * (self.aplsh - self.plafond) / self.plafond, 0.0
            )


def calculer(plafond, n_total, p, saison, dose=None, plafond_azote_total=None):
    """Point d'entrée unique du calcul APLSH (cf. formule en tête de module).

    `plafond_azote_total` : borne additionnelle en kg N total/ha (ex : les
    170 kg des effluents d'élevage) ; None = pas de borne."""
    return ResultatAPLSH(
        plafond=plafond,
        n_total=n_total,
        p=p,
        saison=saison,
        dose=dose,
        plafond_azote_total=plafond_azote_total,
    )
