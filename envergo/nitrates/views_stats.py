"""Page « Statistiques » du pied de page (#517).

Texte de présentation éditable en admin (ContenuRichDSFR `page.stats`) +
graphe du nombre de simulations par semaine ou par mois, lu dans Matomo
(cf. stats_matomo). Graphe en SVG calculé côté serveur : pas de JS, pas de
ressource externe, et un tableau de données en alternative (RGAA).
"""

from django.views.generic import TemplateView

from envergo.nitrates.stats_matomo import simulations_par_periode

PERIODES = {
    "semaine": ("week", "Par semaine"),
    "mois": ("month", "Par mois"),
}
TEXTES_PERIODE = {
    "semaine": ("par semaine", "Semaine"),
    "mois": ("par mois", "Mois"),
}


def simulations(n):
    """« 0 simulation », « 1 simulation », « 2 simulations » (accord français)."""
    return f"{n} simulation{'s' if n > 1 else ''}"


# Géométrie du graphe (unités du viewBox, mis à l'échelle en CSS).
LARGEUR = 720
HAUTEUR = 240
MARGE_GAUCHE = 40
MARGE_BAS = 28
MARGE_HAUT = 12
NB_GRADUATIONS = 4


def _pas_axe(maximum):
    """Pas « rond » (1, 2, 5 x 10^n) pour ~NB_GRADUATIONS graduations."""
    brut = max(maximum, 1) / NB_GRADUATIONS
    puissance = 1
    while puissance * 10 <= brut:
        puissance *= 10
    for facteur in (1, 2, 5, 10):
        if facteur * puissance >= brut:
            return facteur * puissance
    return 10 * puissance


def geometrie(points):
    """Barres et graduations du graphe, en coordonnées du viewBox."""
    if not points:
        return None
    maximum = max(p.simulations for p in points)
    pas = _pas_axe(maximum)
    # On s'arrête à la graduation juste au-dessus du max (45 -> 60, pas 80).
    nb_graduations = max(1, -(-maximum // pas))
    plafond = pas * nb_graduations
    zone_h = HAUTEUR - MARGE_HAUT - MARGE_BAS
    zone_l = LARGEUR - MARGE_GAUCHE
    slot = zone_l / len(points)
    largeur_barre = max(min(slot * 0.6, 48), 2)
    # Une étiquette sur n : pas de chevauchement au-delà de ~16 périodes.
    saut_etiquette = max(1, round(len(points) / 12))
    barres = []
    for i, p in enumerate(points):
        h = zone_h * p.simulations / plafond
        x = MARGE_GAUCHE + i * slot + (slot - largeur_barre) / 2
        barres.append(
            {
                "point": p,
                "titre": f"{p.libelle_long} : {simulations(p.simulations)}",
                "x": round(x, 1),
                "y": round(MARGE_HAUT + zone_h - h, 1),
                "largeur": round(largeur_barre, 1),
                "hauteur": round(h, 1),
                "centre": round(x + largeur_barre / 2, 1),
                "etiquette": i % saut_etiquette == 0,
            }
        )
    graduations = [
        {
            "valeur": pas * k,
            "y": round(MARGE_HAUT + zone_h * (1 - k / nb_graduations), 1),
        }
        for k in range(nb_graduations + 1)
    ]
    return {
        "largeur": LARGEUR,
        "hauteur": HAUTEUR,
        "x_axe": MARGE_GAUCHE,
        "y_base": HAUTEUR - MARGE_BAS,
        "y_etiquettes": HAUTEUR - MARGE_BAS + 18,
        "barres": barres,
        "graduations": graduations,
    }


class StatsView(TemplateView):
    template_name = "nitrates/stats.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        choix = self.request.GET.get("periode", "semaine")
        if choix not in PERIODES:
            choix = "semaine"
        periode_matomo, _libelle = PERIODES[choix]
        points = simulations_par_periode(periode_matomo)
        total = sum(p.simulations for p in points) if points else None
        context.update(
            {
                "titre": "Statistiques",
                "periode": choix,
                "periodes": [(cle, libelle) for cle, (_p, libelle) in PERIODES.items()],
                "points": points,
                "total": total,
                "total_libelle": "simulations" if total and total > 1 else "simulation",
                "periode_texte": TEXTES_PERIODE[choix][0],
                "colonne_periode": TEXTES_PERIODE[choix][1],
                "graphe": geometrie(points) if points else None,
            }
        )
        return context
