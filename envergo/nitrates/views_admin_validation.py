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

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from envergo.nitrates.models import BrancheValidation


@staff_member_required
def validation_index(request):
    """Tableau d'overview de toutes les validations."""
    branches = BrancheValidation.objects.all()
    stats = {
        "total": branches.count(),
        "valide": branches.filter(statut=BrancheValidation.STATUT_VALIDE).count(),
        "a_corriger": branches.filter(
            statut=BrancheValidation.STATUT_A_CORRIGER
        ).count(),
        "non_valide": branches.filter(
            statut=BrancheValidation.STATUT_NON_VALIDE
        ).count(),
    }
    ctx = {
        "branches": branches,
        "stats": stats,
    }
    return render(request, "nitrates_admin/validation/index.html", ctx)


@staff_member_required
def validation_detail(request, pk):
    """Detail d'une feuille avec les 4 colonnes (Miro, YAML, Simulateur,
    Playwright) cote a cote."""
    branche = get_object_or_404(BrancheValidation, pk=pk)
    return render(
        request,
        "nitrates_admin/validation/detail.html",
        {"branche": branche},
    )


@require_POST
@staff_member_required
def validation_set_statut(request, pk):
    """Action HTMX : update statut + commentaire."""
    branche = get_object_or_404(BrancheValidation, pk=pk)
    statut = request.POST.get("statut", "").strip()
    if statut not in dict(BrancheValidation.STATUT_CHOICES):
        return redirect("nitrates_admin_validation_detail", pk=pk)
    branche.statut = statut
    branche.commentaire = request.POST.get("commentaire", "").strip()
    if statut == BrancheValidation.STATUT_VALIDE:
        branche.valide_par = request.user
        branche.valide_at = timezone.now()
    else:
        # On garde l'historique du dernier "valide" mais on n'efface pas
        # tant qu'on n'invalide pas explicitement.
        if statut == BrancheValidation.STATUT_NON_VALIDE:
            branche.valide_par = None
            branche.valide_at = None
    branche.save(
        update_fields=[
            "statut",
            "commentaire",
            "valide_par",
            "valide_at",
            "updated_at",
        ]
    )
    return redirect("nitrates_admin_validation_detail", pk=pk)


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
