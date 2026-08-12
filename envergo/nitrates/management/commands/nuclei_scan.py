"""Scan de securite Nuclei (ProjectDiscovery) contre l'app nitrates -- LOCAL ONLY.

Spike securite #97. Lance le scanner de vulnerabilites Nuclei contre une cible
HTTP (par defaut l'app locale), et ecrit un rapport horodate dans un dossier
LOCAL, jamais commite (cf. .gitignore) et jamais execute en CI : les rapports
Nuclei exposent des details de securite qui ne doivent pas devenir publics.

Nuclei est installe dans l'image de dev (compose/django/Dockerfile, garde
BUILD_ENV=local -- la prod Scalingo build via buildpacks, pas ce Dockerfile).
En repli, si le binaire `nuclei` est absent du PATH, on utilise l'image Docker
officielle `projectdiscovery/nuclei` (necessite alors le socket Docker).

Le dernier rapport est consultable depuis l'admin (page "Rapports Nuclei").

Usage (depuis le conteneur, ex. `docker compose exec django ...`) :
    python manage.py nuclei_scan                          # cible l'app locale
    python manage.py nuclei_scan --target https://staging # scan de staging
    python manage.py nuclei_scan --severity medium,high,critical
"""

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

# Dossier LOCAL des rapports (gitignore). Sous ROOT_DIR pour rester dans le repo
# de travail sans etre versionne.
REPORTS_DIR = Path(settings.ROOT_DIR) / "nuclei_reports"

# Cible par defaut : l'app servie en local. La commande tourne DANS le conteneur
# django (`docker compose exec/run django`), donc l'app est joignable via le nom
# de service `django` sur son port interne 8000 (DNS reseau compose). Pilotable
# par env / argument (ex: --target http://localhost:8000 si nuclei sur le host).
DEFAULT_TARGET = getattr(settings, "NUCLEI_DEFAULT_TARGET", "http://django:8000")

DOCKER_IMAGE = "projectdiscovery/nuclei:latest"


class Command(BaseCommand):
    help = "Lance un scan de securite Nuclei (LOCAL ONLY). Rapport non commite."

    def add_arguments(self, parser):
        parser.add_argument(
            "--target",
            default=DEFAULT_TARGET,
            help=f"URL cible du scan (defaut: {DEFAULT_TARGET}).",
        )
        parser.add_argument(
            "--severity",
            default="low,medium,high,critical",
            help="Niveaux de severite a rapporter (defaut: low..critical).",
        )
        parser.add_argument(
            "--force-docker",
            action="store_true",
            help="Force l'usage de l'image Docker meme si nuclei est installe.",
        )

    def handle(self, *args, **options):
        # Garde-fou : ne JAMAIS tourner en CI (rapports = donnees publiques
        # sensibles). On refuse si un marqueur d'environnement CI est present.
        if self._is_ci():
            raise CommandError(
                "nuclei_scan est interdit en CI (rapport public sensible). "
                "Cette commande ne doit tourner qu'en local."
            )

        target = options["target"]
        severity = options["severity"]

        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        run_dir = REPORTS_DIR / stamp
        run_dir.mkdir()
        jsonl_path = run_dir / "findings.jsonl"

        runner = self._resolve_runner(options["force_docker"])
        self.stdout.write(
            self.style.WARNING(
                f"Scan Nuclei -> {target} (severite: {severity}) via {runner['label']}"
            )
        )

        cmd = self._build_command(runner, target, severity, jsonl_path)
        try:
            subprocess.run(cmd, check=False)
        except FileNotFoundError as exc:
            raise CommandError(
                f"Impossible de lancer le scan ({exc}). Installe nuclei "
                "(https://github.com/projectdiscovery/nuclei) ou Docker."
            )

        findings = self._parse_findings(jsonl_path)
        html_path = run_dir / "report.html"
        self._write_html_report(html_path, target, severity, findings, stamp)
        # Pointeur "dernier rapport" pour l'admin (symlink relatif, robuste).
        self._update_latest_pointer(run_dir)

        self.stdout.write(
            self.style.SUCCESS(f"{len(findings)} finding(s). Rapport : {html_path}")
        )

    def _is_ci(self):
        import os

        return any(
            os.environ.get(var)
            for var in ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "JENKINS_URL")
        )

    def _resolve_runner(self, force_docker):
        """Choisit nuclei local, sinon Docker."""
        if not force_docker and shutil.which("nuclei"):
            return {"kind": "binary", "label": "nuclei (local)"}
        if shutil.which("docker"):
            return {"kind": "docker", "label": DOCKER_IMAGE}
        raise CommandError(
            "Ni `nuclei` ni `docker` trouves dans le PATH. Installe l'un des "
            "deux : https://github.com/projectdiscovery/nuclei"
        )

    def _build_command(self, runner, target, severity, jsonl_path):
        if runner["kind"] == "binary":
            return [
                "nuclei",
                "-target",
                target,
                "-severity",
                severity,
                "-jsonl-export",
                str(jsonl_path),
                "-no-color",
            ]
        # Docker : on monte le dossier du run pour recuperer l'export.
        run_dir = jsonl_path.parent
        return [
            "docker",
            "run",
            "--rm",
            "--add-host",
            "host.docker.internal:host-gateway",
            "-v",
            f"{run_dir}:/out",
            DOCKER_IMAGE,
            "-target",
            target,
            "-severity",
            severity,
            "-jsonl-export",
            "/out/findings.jsonl",
            "-no-color",
        ]

    def _parse_findings(self, jsonl_path):
        findings = []
        if not jsonl_path.exists():
            return findings
        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                findings.append(self._normalize(json.loads(line)))
            except json.JSONDecodeError:
                continue
        return findings

    def _normalize(self, finding):
        """Aplatit les cles utiles au template.

        Nuclei sort des cles avec tirets (`template-id`, `matched-at`) que le
        moteur de template Django ne peut pas atteindre en notation point
        (le `-` est lu comme un operateur). On expose des alias sans tiret.
        """
        info = finding.get("info", {}) or {}
        return {
            "severity": (info.get("severity") or "info"),
            "template_id": finding.get("template-id") or finding.get("templateID", "-"),
            "name": info.get("name", "-"),
            "matched_at": (
                finding.get("matched-at")
                or finding.get("matched_at")
                or finding.get("host", "-")
            ),
        }

    def _write_html_report(self, html_path, target, severity, findings, stamp):
        from django.template.loader import render_to_string

        # Tri par severite decroissante pour lecture rapide.
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        findings_sorted = sorted(
            findings,
            key=lambda f: order.get(f.get("severity", "info"), 5),
        )
        html = render_to_string(
            "nitrates/nuclei_report.html",
            {
                "target": target,
                "severity": severity,
                "stamp": stamp,
                "findings": findings_sorted,
                "count": len(findings_sorted),
            },
        )
        html_path.write_text(html, encoding="utf-8")

    def _update_latest_pointer(self, run_dir):
        latest = REPORTS_DIR / "latest"
        try:
            if latest.is_symlink() or latest.exists():
                latest.unlink()
            latest.symlink_to(run_dir.name)
        except OSError:
            # FS sans symlink : on ecrit un fichier pointeur en repli.
            (REPORTS_DIR / "latest.txt").write_text(run_dir.name, encoding="utf-8")
