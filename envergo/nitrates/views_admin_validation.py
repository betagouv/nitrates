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

from envergo.nitrates.models import BrancheValidation, BrancheValidationAction


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
        "code_pc_miro": 20,
    }
    updated = []
    for f, max_len in fields_allowed.items():
        if f in request.POST:
            val = request.POST.get(f, "")[:max_len]
            setattr(branche, f, val)
            updated.append(f)
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
