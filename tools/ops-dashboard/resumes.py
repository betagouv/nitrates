"""Résumés en langage naturel des différences, par un modèle de langage (CLI `claude`).

Un résumé par paire orientée (ancien texte -> nouveau texte), mis en cache
sur le poste par empreintes : un diff déjà résumé ne repart jamais. La
génération tourne en tâche de fond, la page affiche les résumés au fil de
l'eau.

Passe par la CLI `claude -p` du poste (compte de Max), sans outils, sans MCP,
sans réglages utilisateur, et sans les secrets du pool dans l'environnement.
Le texte envoyé est le diff du contenu réglementaire (pas de données
personnelles, hors noms éventuels dans les contenus eux-mêmes).
"""

import difflib
import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from executeur import env_sans_secrets

MAX_DIFF = 14000
CONSIGNE = (
    "Tu résumes la différence entre deux versions d'un objet du simulateur réglementaire "
    "nitrates (arbre de décision, code de prescription PC, contenu éditorial ou référentiel). "
    "Réponds en français, en une ou deux phrases courtes (300 caractères au plus), factuelles, "
    "sans préambule, sans formule de politesse, sans markdown. Dis ce qui a été ajouté, retiré "
    "ou reformulé, et sur quel sujet (période, seuil, culture, condition, texte affiché). "
    "N'invente rien qui ne soit pas dans le diff. N'utilise jamais de tiret long."
)


class Resumeur:
    def __init__(self, cache: Path, actif=True, modele="sonnet", paralleles=3):
        self.cache_path = cache
        self.actif = actif
        self.modele = modele
        self.verrou = threading.Lock()
        self.version = 0
        self.en_cours = set()
        try:
            self.cache = json.loads(cache.read_text())
        except (OSError, ValueError):
            self.cache = {}
        self.pool = ThreadPoolExecutor(
            max_workers=paralleles, thread_name_prefix="resume"
        )

    def etat(self):
        with self.verrou:
            out = dict(self.cache)
            for cle in self.en_cours:
                out[cle] = {"en_cours": True}
            return out

    def demander(self, cle, objet, libelle_ancien, libelle_nouveau, ancien, nouveau):
        if not self.actif or ancien is None or nouveau is None:
            return
        with self.verrou:
            if cle in self.cache or cle in self.en_cours:
                return
            self.en_cours.add(cle)
            self.version += 1
        self.pool.submit(
            self._generer, cle, objet, libelle_ancien, libelle_nouveau, ancien, nouveau
        )

    def _generer(self, cle, objet, libelle_ancien, libelle_nouveau, ancien, nouveau):
        diff = "\n".join(
            difflib.unified_diff(
                ancien.splitlines(), nouveau.splitlines(), lineterm="", n=2
            )
        )
        if len(diff) > MAX_DIFF:
            diff = diff[:MAX_DIFF] + "\n[diff tronqué]"
        invite = (
            f"Objet : {objet}.\nAncienne version : {libelle_ancien}.\nNouvelle version : {libelle_nouveau}.\n"
            f"Diff unifié (lignes « - » : ancienne, « + » : nouvelle) :\n{diff}"
        )
        try:
            p = subprocess.run(
                [
                    "claude",
                    "-p",
                    "--model",
                    self.modele,
                    "--strict-mcp-config",
                    "--no-session-persistence",
                    "--setting-sources",
                    "",
                    "--tools",
                    "",
                    "--system-prompt",
                    CONSIGNE,
                ],  # fmt: skip
                input=invite,
                capture_output=True,
                text=True,
                timeout=120,
                env=env_sans_secrets(),
            )
            texte = p.stdout.strip().replace("—", ",").replace("–", "-")
            res = (
                {"texte": texte}
                if p.returncode == 0 and texte
                else {"erreur": (p.stderr or p.stdout).strip()[-300:]}
            )
        except Exception as e:  # noqa: BLE001
            res = {"erreur": repr(e)[:300]}
        with self.verrou:
            self.en_cours.discard(cle)
            self.cache[cle] = res
            self.version += 1
            try:
                tmp = self.cache_path.with_suffix(".tmp")
                # On ne garde sur disque que les résumés réussis : une erreur
                # (réseau, quota) sera retentée au prochain lancement.
                durables = {k: v for k, v in self.cache.items() if "texte" in v}
                tmp.write_text(json.dumps(durables, ensure_ascii=False))
                tmp.replace(self.cache_path)
            except OSError:
                pass
