"""Vues admin pour la validation manuelle des feuilles de l'arbre.

Tableau qui croise pour chaque feuille `culture_principale` :
  - chemin metier (label)
  - extrait YAML (regle au seed)
  - lien deeplink simulateur
  - screenshot Miro (uploade par Max)
  - screenshot Playwright (auto-capture)
  - statut validation + commentaire

Cf. issue #28 / sprint MVP-1 fin.
"""

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db import IntegrityError
from django.db.models import Max, Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from envergo.nitrates.models import BrancheValidation, BrancheValidationAction


@staff_member_required
def validation_index(request):
    """Tableau d'overview de toutes les validations."""
    # Prefetch sur `actions__user` : evite le N+1 cause par
    # `branche.actions_par_user` appele dans le template pour chaque ligne.
    # On ordonne le prefetch comme `actions_par_user` (created_at ASC) pour
    # qu'il reutilise le cache (sinon Django refait une requete).
    # Avant : 1 + N requetes actions + M requetes users (~50+ pour 41 lignes).
    # Apres : 1 + 2 requetes (actions + users) au total.
    actions_qs = BrancheValidationAction.objects.order_by("created_at").select_related(
        "user"
    )
    # Ordre = ordre d'insertion au seed = ordre du board Miro (champ `ordre`,
    # cf. BrancheValidation.Meta.ordering). On le RÉAFFIRME explicitement ici
    # pour que le filtre scope/nature préserve toujours la séquence Miro
    # arbre par arbre (suivi côte à côte avec le board), même si un futur
    # refactor du prefetch venait masquer le Meta.ordering.
    base = BrancheValidation.objects.prefetch_related(
        Prefetch("actions", queryset=actions_qs)
    ).order_by("ordre", "chemin_yaml")

    # Deux axes de filtres ORTHOGONAUX et combinables (cf. carte #140) :
    #   - scope  : PAN / PAR Grand Est / ZAR Grand Est
    #   - nature : couvert d'interculture / culture principale
    # Chaque axe a un param GET (`?scope=`, `?nature=`) qu'on croise. Ca
    # autorise n'importe quelle combinaison (ex: PAR x couvert), au lieu de
    # filtres pre-combines qui ferment les associations possibles.
    SCOPES = [
        ("national", "PAN"),
        ("par_grand_est", "PAR Grand Est"),
        ("zar_grand_est", "ZAR Grand Est"),
    ]
    NATURES = [
        ("couvert", "Couvert"),
        ("culture_principale", "Culture principale"),
    ]
    scope_actif = request.GET.get("scope", "")
    nature_actif = request.GET.get("nature", "")

    branches = base
    if scope_actif in dict(SCOPES):
        branches = branches.filter(scope=scope_actif)
    if nature_actif in dict(NATURES):
        branches = branches.filter(nature=nature_actif)

    # Compteurs par valeur d'axe, en respectant le filtre de L'AUTRE axe
    # (ainsi le badge « couvert » reflète bien le scope déjà sélectionné).
    base_scope = (
        base.filter(nature=nature_actif) if nature_actif in dict(NATURES) else base
    )
    base_nature = (
        base.filter(scope=scope_actif) if scope_actif in dict(SCOPES) else base
    )
    scopes_ctx = [
        (cle, label, base_scope.filter(scope=cle).count()) for cle, label in SCOPES
    ]
    natures_ctx = [
        (cle, label, base_nature.filter(nature=cle).count()) for cle, label in NATURES
    ]

    stats = {
        "total": branches.count(),
        "valide": branches.filter(statut=BrancheValidation.STATUT_VALIDE).count(),
        "a_corriger": branches.filter(
            statut=BrancheValidation.STATUT_A_CORRIGER
        ).count(),
        "non_valide": branches.filter(
            statut=BrancheValidation.STATUT_NON_VALIDE
        ).count(),
        "flag_verif": branches.filter(flag_verif=True).count(),
    }
    ctx = {
        "branches": branches,
        "stats": stats,
        "scopes": scopes_ctx,
        "natures": natures_ctx,
        "scope_actif": scope_actif,
        "nature_actif": nature_actif,
        "miro_board_id": settings.NITRATES_MIRO_BOARD_ID,
    }
    return render(request, "nitrates_admin/validation/index.html", ctx)


@staff_member_required
def validation_create(request):
    """Ajout manuel d'une ligne de validation.

    Le seed cree les lignes automatiquement depuis l'arbre, mais Max doit
    pouvoir en ajouter a la main (feuille oubliee, cas exotique a tracer hors
    arbre, etc.). Seul `chemin_yaml` est obligatoire (cle naturelle unique) ;
    les autres champs sont editables ensuite via la page detail (edit-meta).

    GET  -> formulaire vide.
    POST -> creation puis redirect vers la page detail de la nouvelle ligne.
    """
    if request.method == "POST":
        chemin_yaml = request.POST.get("chemin_yaml", "").strip()
        if not chemin_yaml:
            messages.error(request, "Le champ « chemin YAML » est obligatoire.")
            return render(
                request,
                "nitrates_admin/validation/create.html",
                {"data": request.POST},
            )

        # Ordre par defaut : a la fin de la liste (apres le max existant).
        ordre_max = BrancheValidation.objects.aggregate(m=Max("ordre"))["m"] or 0
        regle_id = request.POST.get("regle_id", "").strip()[:200]
        branche_label = request.POST.get("branche_label", "").strip()[:500]
        # branche_label a un help_text mais pas de blank=True : on retombe sur
        # le dernier segment du chemin si Max ne le renseigne pas.
        if not branche_label:
            branche_label = chemin_yaml.rsplit("/", 1)[-1]

        try:
            branche = BrancheValidation.objects.create(
                chemin_yaml=chemin_yaml,
                ordre=ordre_max + 1,
                regle_id=regle_id,
                branche_label=branche_label,
                branche_miro=request.POST.get("branche_miro", "").strip()[:200],
                type_fertilisant_miro=request.POST.get(
                    "type_fertilisant_miro", ""
                ).strip()[:50],
                resultat_miro=request.POST.get("resultat_miro", "").strip()[:500],
                code_pc_miro=request.POST.get("code_pc_miro", "").strip()[:300],
                url_simulateur=request.POST.get("url_simulateur", "").strip()[:2000],
            )
        except IntegrityError:
            messages.error(
                request,
                f"Une ligne existe déjà pour le chemin YAML « {chemin_yaml} ».",
            )
            return render(
                request,
                "nitrates_admin/validation/create.html",
                {"data": request.POST},
            )

        messages.success(request, "Ligne de validation créée.")
        return redirect("nitrates_admin_validation_detail", pk=branche.pk)

    return render(request, "nitrates_admin/validation/create.html", {"data": {}})


@require_POST
@staff_member_required
def validation_delete(request, pk):
    """Suppression manuelle d'une ligne de validation (+ ses actions en
    cascade via le FK). Reserve aux lignes ajoutees a la main ou obsoletes ;
    un re-seed recreera les lignes legitimes issues de l'arbre."""
    branche = get_object_or_404(BrancheValidation, pk=pk)
    label = branche.regle_id or branche.chemin_yaml
    branche.delete()
    messages.success(request, f"Ligne « {label} » supprimée.")
    return redirect("nitrates_admin_validation_index")


@staff_member_required
def validation_detail(request, pk):
    """Detail d'une feuille avec les 4 colonnes (Miro, YAML, Simulateur,
    Playwright) cote a cote."""
    # Prefetch les actions + leur user pour eviter le N+1 dans le bloc
    # d'historique des validations (1 + 1 query au lieu de 1 + N + N).
    qs = BrancheValidation.objects.prefetch_related(
        Prefetch(
            "actions",
            queryset=BrancheValidationAction.objects.select_related("user").order_by(
                "created_at"
            ),
        )
    )
    branche = get_object_or_404(qs, pk=pk)
    return render(
        request,
        "nitrates_admin/validation/detail.html",
        {
            "branche": branche,
            "miro_board_id": settings.NITRATES_MIRO_BOARD_ID,
        },
    )


@require_POST
@staff_member_required
def validation_set_statut(request, pk):
    """Ajoute une action de validation par l'utilisateur courant.

    Multi-validation : on n'ecrase pas les validations precedentes des
    autres users. Chaque action est conservee. Le statut courant de la
    BrancheValidation = celui de la derniere action (en date).
    """
    branche = get_object_or_404(BrancheValidation, pk=pk)
    statut = request.POST.get("statut", "").strip()
    if statut not in dict(BrancheValidation.STATUT_CHOICES):
        return redirect("nitrates_admin_validation_detail", pk=pk)
    commentaire = request.POST.get("commentaire", "").strip()
    BrancheValidationAction.objects.create(
        branche=branche,
        user=request.user,
        statut=statut,
        commentaire=commentaire,
    )
    # Denormalise le statut sur la branche pour faciliter le filtrage SQL.
    branche.statut = statut
    branche.save(update_fields=["statut", "updated_at"])
    return redirect("nitrates_admin_validation_index")


@require_POST
@staff_member_required
def validation_upload_miro(request, pk):
    """Upload du screenshot Miro (override du PNG auto-attache)."""
    branche = get_object_or_404(BrancheValidation, pk=pk)
    f = request.FILES.get("screenshot_miro")
    if f:
        branche.screenshot_miro = f
        branche.save(update_fields=["screenshot_miro", "updated_at"])
    return redirect("nitrates_admin_validation_detail", pk=pk)


@require_POST
@staff_member_required
def validation_upload_yaml_viewer(request, pk):
    """Upload du screenshot admin YAML viewer scrolle sur la feuille."""
    branche = get_object_or_404(BrancheValidation, pk=pk)
    f = request.FILES.get("screenshot_yaml_viewer")
    if f:
        branche.screenshot_yaml_viewer = f
        branche.save(update_fields=["screenshot_yaml_viewer", "updated_at"])
    return redirect("nitrates_admin_validation_detail", pk=pk)


@require_POST
@staff_member_required
def validation_upload_yaml_form(request, pk):
    """Upload du screenshot admin form d'edition (cas tricky)."""
    branche = get_object_or_404(BrancheValidation, pk=pk)
    f = request.FILES.get("screenshot_yaml_form")
    if f:
        branche.screenshot_yaml_form = f
        branche.save(update_fields=["screenshot_yaml_form", "updated_at"])
    return redirect("nitrates_admin_validation_detail", pk=pk)


@require_POST
@staff_member_required
def validation_edit_meta(request, pk):
    """Edition manuelle des champs textuels (URL simulateur, snapshot YAML,
    résultat Miro attendu, code PC).

    Permet a Max de corriger ce que le seed a mal genere sans repasser
    par un re-seed complet (qui peut casser les autres lignes deja
    validees)."""
    branche = get_object_or_404(BrancheValidation, pk=pk)
    fields_allowed = {
        "url_simulateur": 2000,
        "yaml_snapshot": 50000,
        "resultat_miro": 500,
        "code_pc_miro": 300,
        "miro_widget_id": 40,
        "note_verif": 2000,
    }
    updated = []
    for f, max_len in fields_allowed.items():
        if f in request.POST:
            val = request.POST.get(f, "")[:max_len]
            setattr(branche, f, val)
            updated.append(f)
    # `flag_verif` est une checkbox : absente du POST = decochee. On ne
    # l'applique que si le form de flag a ete soumis (detecte via la
    # presence de `note_verif`), pour ne pas l'ecraser depuis un autre form.
    if "note_verif" in request.POST:
        branche.flag_verif = request.POST.get("flag_verif") == "1"
        updated.append("flag_verif")
    if updated:
        updated.append("updated_at")
        branche.save(update_fields=updated)
    return redirect("nitrates_admin_validation_detail", pk=pk)


@require_POST
@staff_member_required
def validation_upload_playwright(request, pk):
    """Upload du screenshot Playwright resultat simulateur (devops manuel)."""
    branche = get_object_or_404(BrancheValidation, pk=pk)
    f = request.FILES.get("screenshot_playwright")
    if f:
        branche.screenshot_playwright = f
        branche.playwright_run_at = timezone.now()
        branche.save(
            update_fields=[
                "screenshot_playwright",
                "playwright_run_at",
                "updated_at",
            ]
        )
    return redirect("nitrates_admin_validation_detail", pk=pk)
