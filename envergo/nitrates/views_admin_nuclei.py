"""Admin de consultation des rapports de scan Nuclei (spike securite #97).

Le scan tourne via `python manage.py nuclei_scan` et ecrit ses rapports dans un
dossier LOCAL non versionne (cf. .gitignore). Cette vue liste les rapports
disponibles et affiche le dernier -- LOCAL ONLY.

Garde-fou : la vue refuse de servir quoi que ce soit hors environnement local
(DEBUG). Les rapports Nuclei exposent des details de securite ; ils ne doivent
jamais etre exposes sur staging/prod, meme derriere l'admin.
"""

from pathlib import Path

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import Http404, HttpResponse
from django.shortcuts import render

REPORTS_DIR = Path(settings.ROOT_DIR) / "nuclei_reports"


def _local_only():
    """Les rapports ne sont consultables qu'en local (DEBUG)."""
    return getattr(settings, "DEBUG", False)


def _list_runs():
    """Liste les dossiers de run (horodates), du plus recent au plus ancien."""
    if not REPORTS_DIR.exists():
        return []
    runs = [
        d for d in REPORTS_DIR.iterdir() if d.is_dir() and (d / "report.html").exists()
    ]
    return sorted(runs, key=lambda d: d.name, reverse=True)


@staff_member_required
def nuclei_index(request):
    """Liste des rapports + lien vers chacun."""
    if not _local_only():
        raise Http404("Rapports Nuclei disponibles en local uniquement.")
    runs = _list_runs()
    context = {
        "runs": [{"name": r.name} for r in runs],
        "has_reports": bool(runs),
        "reports_dir": str(REPORTS_DIR),
    }
    return render(request, "nitrates/nuclei_admin_index.html", context)


@staff_member_required
def nuclei_report(request, stamp):
    """Sert le rapport HTML d'un run donne (ou 'latest' pour le dernier)."""
    if not _local_only():
        raise Http404("Rapports Nuclei disponibles en local uniquement.")

    if stamp == "latest":
        runs = _list_runs()
        if not runs:
            raise Http404("Aucun rapport Nuclei genere.")
        run_dir = runs[0]
    else:
        # Garde-fou path traversal : on n'accepte qu'un nom de dossier direct.
        candidate = (REPORTS_DIR / stamp).resolve()
        if candidate.parent != REPORTS_DIR.resolve() or not candidate.is_dir():
            raise Http404("Rapport introuvable.")
        run_dir = candidate

    html_file = run_dir / "report.html"
    if not html_file.exists():
        raise Http404("Rapport introuvable.")
    return HttpResponse(html_file.read_text(encoding="utf-8"))
