"""Admin du bornage géographique du simulateur (carte #57).

Panel drag&drop : deux colonnes « Ouvert » / « Fermé », départements
regroupés par région. Glisser un département d'une colonne à l'autre bascule
son `est_ouvert`. Persistance htmx (POST par département).

Vit dans l'app nitrates (comme l'éditeur d'arbre YAML), accessible depuis le
header de l'admin nitrates.
"""

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from envergo.nitrates.models import DepartementOuverture


def _liste_avec_entetes(departements):
    """Transforme une liste plate de départements (triés par région) en une
    liste d'items pour le template : chaque changement de région insère un
    item « en-tête » avant les départements de cette région.

    Retourne une liste d'objets dict :
      - {"type": "entete", "region_label": ..., "region_code": ...}
      - {"type": "dept", "dept": DepartementOuverture}

    Tout est dans UNE seule liste plate (une <ul> par colonne) : le drag&drop
    inter-colonnes a toujours une zone de drop, contrairement à une <ul> par
    région (cf. refonte carte #57).
    """
    items = []
    region_courante = None
    for dept in departements:
        if dept.region_code != region_courante:
            region_courante = dept.region_code
            items.append(
                {
                    "type": "entete",
                    "region_label": dept.region_label or "(sans région)",
                    "region_code": dept.region_code,
                }
            )
        items.append({"type": "dept", "dept": dept})
    return items


@staff_member_required
@ensure_csrf_cookie
def ouverture_index(request):
    """Page principale du panel d'ouverture géographique.

    `ensure_csrf_cookie` : le drag&drop POST en fetch (pas via un form Django),
    il a besoin que le cookie `csrftoken` soit posé au chargement de la page
    pour pouvoir l'envoyer dans l'en-tête X-CSRFToken.
    """
    qs = DepartementOuverture.objects.all().order_by(
        "region_label", "ordre_affichage", "code"
    )
    ouverts = [d for d in qs if d.est_ouvert]
    fermes = [d for d in qs if not d.est_ouvert]
    return render(
        request,
        "nitrates_admin/ouverture/index.html",
        {
            "items_ouverts": _liste_avec_entetes(ouverts),
            "items_fermes": _liste_avec_entetes(fermes),
            "nb_ouverts": len(ouverts),
            "nb_fermes": len(fermes),
        },
    )


@staff_member_required
@require_POST
def ouverture_toggle(request):
    """Bascule l'état d'un département (POST htmx depuis le drag&drop).

    Paramètres POST :
      - code : code du département
      - est_ouvert : "true" / "false" (état cible)

    Renvoie un fragment vide + un HX-Trigger toast. Le DOM est déjà à jour
    côté client (SortableJS a déplacé l'élément) ; on ne fait que persister.
    """
    code = (request.POST.get("code") or "").strip()
    cible = (request.POST.get("est_ouvert") or "").strip().lower()
    if not code or cible not in ("true", "false"):
        return HttpResponseBadRequest("Paramètres invalides.")

    est_ouvert = cible == "true"
    updated = DepartementOuverture.objects.filter(code=code).update(
        est_ouvert=est_ouvert
    )
    if not updated:
        return HttpResponseBadRequest(f"Département {code!r} inconnu.")

    etat = "ouvert" if est_ouvert else "fermé"
    resp = HttpResponse(status=204)
    resp["HX-Trigger"] = '{"showToast": {"message": "Département %s : %s"}}' % (
        code,
        etat,
    )
    return resp


@staff_member_required
@require_POST
def ouverture_toggle_region(request):
    """Ouvre ou ferme TOUS les départements d'une région d'un coup.

    Paramètres POST :
      - region_code : code région
      - est_ouvert : "true" / "false"

    Renvoie la page entière re-rendue (HX-Refresh) pour repositionner les
    départements dans les bonnes colonnes.
    """
    region_code = (request.POST.get("region_code") or "").strip()
    cible = (request.POST.get("est_ouvert") or "").strip().lower()
    if not region_code or cible not in ("true", "false"):
        return HttpResponseBadRequest("Paramètres invalides.")

    est_ouvert = cible == "true"
    n = DepartementOuverture.objects.filter(region_code=region_code).update(
        est_ouvert=est_ouvert
    )
    etat = "ouverte" if est_ouvert else "fermée"
    resp = HttpResponse(status=204)
    resp["HX-Refresh"] = "true"
    resp["HX-Trigger"] = (
        '{"showToast": {"message": "Région %s %s (%d départements)"}}'
        % (region_code, etat, n)
    )
    return resp
