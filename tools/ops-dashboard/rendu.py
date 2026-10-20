"""Rendu HTML DSFR des contenus riches (PC, contenus éditoriaux), tel que vu par l'usager.

On ne réimplémente pas le rendu : on appelle le compilateur de l'application
(`envergo.nitrates.contenu_rich.compilateur`) dans le conteneur Django local,
bloc par bloc, pour pouvoir signaler dans la page les blocs qui diffèrent entre
deux versions. Les liens de référence (`lien_ref`) sont résolus avec la table
LienReference de l'environnement d'où vient la version, pas celle du local.

Un appel au conteneur par lot de versions (démarrage de Django : 2 à 4 s),
puis cache mémoire par empreinte (blocs + liens).
"""

import hashlib
import json
import secrets
import subprocess
import threading

from executeur import env_sans_secrets

MARQUE = "@@RENDU_OPS@@"

PROGRAMME = r"""
import hashlib as _h
import json as _j

from envergo.nitrates.contenu_rich import compilateur as _c

_entree = _j.load(open(CHEMIN_ENTREE))
_sortie = {}
for _cle, _item in _entree.items():
    _blocs = _item["blocs"]
    if isinstance(_blocs, dict):
        _blocs = _blocs.get("blocs", [])
    _ctx = {"accordion_seq": 0, "id_prefix": "ops-" + _cle[:8], "liens_references": _item["liens"]}
    _morceaux = []
    for _bloc in _blocs or []:
        _sha = _h.sha256(_j.dumps(_bloc, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
        try:
            if hasattr(_c, "_compile_blocs"):
                _html = str(_c._compile_blocs([_bloc], _c.NIVEAU_TITRE_BASE, _ctx))
            else:
                _html = str(_c.compile_dsfr([_bloc], id_prefix="ops-" + _sha))
        except Exception as _e:  # noqa: BLE001
            _html = "<p><strong>Erreur de rendu :</strong> " + str(_e).replace("<", "&lt;") + "</p>"
        _morceaux.append({"sha": _sha, "html": _html, "type": _bloc.get("type") if isinstance(_bloc, dict) else None})
    _sortie[_cle] = _morceaux
print("@@RENDU_OPS@@" + _j.dumps(_sortie, ensure_ascii=False))
"""


def cle_rendu(blocs, liens):
    brut = json.dumps([blocs, liens], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(brut.encode()).hexdigest()[:16]


class Rendeur:
    def __init__(self, conteneur):
        self.conteneur = conteneur
        self.cache = {}
        self.verrou = threading.Lock()

    def rendre(self, items):
        """items : {cle: {"blocs": ..., "liens": {...}}} -> {cle: [blocs rendus]}."""
        with self.verrou:
            manquants = {k: v for k, v in items.items() if k not in self.cache}
        if manquants:
            for k, v in self._appel(manquants).items():
                with self.verrou:
                    self.cache[k] = v
        with self.verrou:
            return {k: self.cache.get(k) for k in items}

    def _appel(self, items):
        env = env_sans_secrets()
        suffixe = secrets.token_hex(4)
        entree, prog = f"/tmp/ops_rendu_{suffixe}.json", f"/tmp/ops_rendu_{suffixe}.py"
        for chemin, contenu in (
            (entree, json.dumps(items, ensure_ascii=False)),
            (prog, PROGRAMME),
        ):
            p = subprocess.run(
                ["docker", "exec", "-i", self.conteneur, "sh", "-c", f"cat > {chemin}"],
                input=contenu,
                text=True,
                capture_output=True,
                env=env,
                timeout=60,
            )
            if p.returncode != 0:
                raise RuntimeError(
                    f"dépôt dans le conteneur : {p.stderr.strip()[-300:]}"
                )
        commande = (
            'export DATABASE_URL="postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:'
            '${POSTGRES_PORT}/${POSTGRES_DB}"; '
            f"exec python manage.py shell -c \"CHEMIN_ENTREE='{entree}'; exec(open('{prog}').read())\""
        )
        p = subprocess.run(
            ["docker", "exec", self.conteneur, "sh", "-c", commande],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        subprocess.run(
            ["docker", "exec", self.conteneur, "rm", "-f", entree, prog],
            capture_output=True,
            env=env,
        )
        for ligne in p.stdout.splitlines():
            if ligne.startswith(MARQUE):
                return json.loads(ligne[len(MARQUE) :])  # noqa: E203
        raise RuntimeError(
            "rendu impossible : " + (p.stderr or p.stdout).strip()[-400:]
        )


def items_pour_ligne(releves, famille, cle):
    """Prépare le rendu de chaque env où l'objet existe (PC ou contenu)."""
    sortie, items = {}, {}
    for env, r in releves.items():
        o = r["familles"].get(famille, {}).get("objets", {}).get(cle)
        if not o:
            continue
        champs = json.loads(r["contenus"][o["texte"]])
        liens = {}
        for ident, lien in (
            r["familles"].get("lienreference", {}).get("objets", {}).items()
        ):
            try:
                liens[ident] = json.loads(r["contenus"][lien["texte"]]).get("url")
            except (KeyError, ValueError):
                pass
        blocs = champs.get("blocs") or []
        if isinstance(blocs, dict):
            blocs = blocs.get("blocs", [])
        k = cle_rendu(blocs, liens)
        items[k] = {"blocs": blocs, "liens": liens}
        sortie[env] = {
            "cle_rendu": k,
            "sha": o["sha"],
            "titre": champs.get("titre_public") or champs.get("mots_cles") or "",
            "texte_court": champs.get("texte_court") or "",
            "a_des_blocs": bool(blocs),
        }
    return sortie, items
