"""Prévisualisation du rendu HTML DSFR d'un contenu riche (carte #136).

Vue staff-only : compile les blocs (d'un CodePrescription ou d'un
ContenuRichDSFR) en HTML DSFR et les rend dans une page propre chargeant le
CSS DSFR + le CSS calendrier/simulateur. Sert à voir le rendu final tel qu'il
apparaîtra côté public, depuis un lien dans l'admin (nouvel onglet).
"""

from django.contrib.admin.views.decorators import staff_member_required
from django.http import Http404
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View

from envergo.nitrates.contenu_rich.compilateur import compile_dsfr


@method_decorator(staff_member_required, name="dispatch")
class ContenuRichPreviewView(View):
    """`/admin/nitrates/contenu-rich/preview/?type=pc&id=...` ou `?type=rich&id=...`.

    type=pc   -> CodePrescription.blocs (id = pk ou identifiant)
    type=rich -> ContenuRichDSFR.blocs (id = pk ou cle)
    """

    def get(self, request):
        from envergo.nitrates.models import CodePrescription, ContenuRichDSFR

        type_ = request.GET.get("type", "")
        ident = request.GET.get("id", "")
        titre = ""
        blocs = None

        if type_ == "pc":
            obj = (
                CodePrescription.objects.filter(pk=ident).first()
                if ident.isdigit()
                else CodePrescription.objects.filter(identifiant=ident).first()
            )
            if obj is None:
                raise Http404("Prescription introuvable")
            blocs = obj.blocs
            titre = f"PC {obj.identifiant.upper()} — {obj.mots_cles}"
        elif type_ == "rich":
            obj = (
                ContenuRichDSFR.objects.filter(pk=ident).first()
                if ident.isdigit()
                else ContenuRichDSFR.objects.filter(cle=ident).first()
            )
            if obj is None:
                raise Http404("Contenu introuvable")
            blocs = obj.blocs
            titre = f"{obj.cle} — {obj.libelle_admin}"
        else:
            raise Http404("type invalide (pc|rich)")

        html = compile_dsfr(blocs or [])
        return render(
            request,
            "nitrates/admin/contenu_rich_preview.html",
            {"contenu_html": html, "titre_preview": titre},
        )
