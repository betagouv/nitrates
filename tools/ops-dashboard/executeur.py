"""Côté poste : fabrique un lot de transferts et l'exécute sur l'env cible.

Le lot est construit à partir des relevés (ce que l'opérateur a vu à
l'écran), avec pour chaque objet l'empreinte de la cible au moment de
l'affichage : apply_lot.py refuse si elle a bougé depuis.

Transport :
- local : `docker exec` dans le conteneur Django (même code que le site local) ;
- Scalingo : one-off `scalingo run --file`, sous pseudo-terminal (le one-off
  attaché exige un TTY), sortie lue en direct.
"""

import base64
import json
import os
import pty
import re
import select
import subprocess
import tempfile
import time
from pathlib import Path

import render

ICI = Path(__file__).resolve().parent
MARQUE_DEBUT = "@@RESULTAT_OPS@@"
MARQUE_FIN = "@@FIN_RESULTAT_OPS@@"
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# Variables transmises aux sous-process qui n'ont pas besoin des secrets du
# pool (docker, claude) : on ne leur passe pas SCALINGO_API_TOKEN & co.
ENV_SURE = (
    "HOME",
    "PATH",
    "USER",
    "LOGNAME",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "SHELL",
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
)


def env_sans_secrets():
    return {k: v for k, v in os.environ.items() if k in ENV_SURE}


class ErreurLot(Exception):
    pass


def construire_lot(releves, ref, source, cible, operations, mode, auteur):
    src, tgt = releves.get(source), releves.get(cible)
    if not src:
        raise ErreurLot(f"pas de relevé pour {source}")
    textes = src.get("contenus", {})
    ops = []
    for op in operations:
        famille, cle = op["famille"], op["cle"]
        if famille == "arbre":
            v = _arbre_actif(src, cle)
            if not v:
                raise ErreurLot(f"{cle} : pas d'arbre actif en {source}")
            logique = json.loads(textes[v["texte_logique"]])
            t = _arbre_actif(tgt, cle) if tgt else None
            ops.append(
                {
                    "famille": famille,
                    "cle": cle,
                    "sha_source": v["sha"],
                    "sha_cible_attendu": t and t["sha"],
                    "config": logique["config"],
                    "contenu": logique["contenu"],
                    "yaml": textes.get(v.get("texte_yaml"), ""),
                    "nom_source": v["nom"],
                    "date_origine": _date_arbre(v),
                }
            )
        else:
            objets = src["familles"].get(famille, {}).get("objets", {})
            o = objets.get(cle)
            if not o:
                raise ErreurLot(f"{famille} {cle} : absent de {source}")
            t = tgt and tgt["familles"].get(famille, {}).get("objets", {}).get(cle)
            ops.append(
                {
                    "famille": famille,
                    "cle": cle,
                    "sha_source": o["sha"],
                    "facettes_source": o["facettes"],
                    "sha_cible_attendu": t and t["sha"],
                    "champs": json.loads(textes[o["texte"]]),
                    "date_origine": render.date_auteur(o.get("dates", []))[0],
                }
            )
    return {
        "ref": ref,
        "source": source,
        "cible": cible,
        "mode": mode,
        "auteur": auteur,
        "operations": ops,
    }


def _date_arbre(v):
    """Date d'écriture d'un arbre actif (une activation par copie ne compte pas)."""
    rev = v.get("derniere_revision") or {}
    ja = v.get("journal_admin") or {}
    if ja.get("copie") and not (rev.get("date") and rev["date"] > ja["date"]):
        return ja["copie"].get("date_origine")
    dates = [x for x in (v.get("active_le"), rev.get("date"), v.get("cree")) if x]
    return max(dates) if dates else None


def _arbre_actif(releve, cle):
    for v in releve["familles"].get("arbre", {}).get("versions", []):
        if v["cle"] == cle and v["statut"] == "active":
            return v
    return None


def programme(lot):
    """collect_snapshot.py (sans son main) + LOT + apply_lot.py, en un seul fichier."""
    releve = (ICI / "collect_snapshot.py").read_text()
    releve = re.sub(r'\nif __name__ == "__main__":\n    main\(\)\n?$', "\n", releve)
    charge = base64.b64encode(json.dumps(lot, ensure_ascii=False).encode()).decode()
    return (
        releve
        + "\nimport base64 as _b64\n"
        + f'LOT = json.loads(_b64.b64decode("{charge}").decode("utf-8"))\n\n'
        + (ICI / "apply_lot.py").read_text()
    )


def lire_resultat(lignes):
    try:
        i = lignes.index(MARQUE_DEBUT)
        j = lignes.index(MARQUE_FIN, i)
        return json.loads("\n".join(lignes[i + 1 : j]))  # noqa: E203
    except (ValueError, json.JSONDecodeError):
        return None


def _flux(proc_lecture, journal, lignes):
    """Lit un flux ligne par ligne, transmet au journal (sauf le bloc résultat)."""
    dans_resultat = False
    for brut in proc_lecture:
        ligne = ANSI.sub("", brut.rstrip("\r\n"))
        lignes.append(ligne)
        if ligne == MARQUE_DEBUT:
            dans_resultat = True
        if not dans_resultat:
            journal(ligne)
        if ligne == MARQUE_FIN:
            dans_resultat = False


def executer_local(conteneur, lot, journal):
    nom = f"/tmp/ops_apply_{lot['ref']}.py"
    p = subprocess.run(
        ["docker", "exec", "-i", conteneur, "sh", "-c", f"cat > {nom}"],
        input=programme(lot),
        text=True,
        capture_output=True,
        env=env_sans_secrets(),
        timeout=60,
    )
    if p.returncode != 0:
        raise ErreurLot(
            f"dépôt du programme dans le conteneur : {p.stderr.strip()[-400:]}"
        )
    journal(f"programme déposé dans {conteneur}:{nom}")
    lignes = []
    # docker exec ne passe pas par l'entrypoint, qui fabrique DATABASE_URL :
    # sans elle, les settings échouent et Django ne s'initialise pas.
    commande = (
        'export DATABASE_URL="postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:'
        '${POSTGRES_PORT}/${POSTGRES_DB}"; '
        f"exec python manage.py shell -c \"exec(open('{nom}').read())\""
    )
    proc = subprocess.Popen(
        ["docker", "exec", conteneur, "sh", "-c", commande],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env_sans_secrets(),
    )
    _flux(proc.stdout, journal, lignes)
    proc.wait()
    subprocess.run(
        ["docker", "exec", conteneur, "rm", "-f", nom],
        capture_output=True,
        env=env_sans_secrets(),
    )
    return lire_resultat(lignes), proc.returncode


def executer_scalingo(region, app, lot, journal, timeout=900):
    with tempfile.TemporaryDirectory(prefix="nitrates-ops-") as dossier:
        prog = Path(dossier) / f"ops_apply_{lot['ref']}.py"
        prog.write_text(programme(lot))
        script = Path(dossier) / f"ops_run_{lot['ref']}.sh"
        script.write_text(
            f"echo 'conteneur prêt, lancement de Django'\n"
            f"python manage.py shell -c \"exec(open('/tmp/uploads/{prog.name}').read())\"\n"
        )
        cmd = [
            "scalingo", "--region", region, "--app", app, "run", "--silent",
            "--file", str(prog), "--file", str(script), "bash", f"/tmp/uploads/{script.name}",
        ]  # fmt: skip
        journal(f"one-off Scalingo sur {app} (démarrage du conteneur, 10 à 40 s)")
        maitre, esclave = pty.openpty()
        proc = subprocess.Popen(
            cmd, stdin=esclave, stdout=esclave, stderr=esclave, close_fds=True
        )
        os.close(esclave)
        lignes, reste, debut, banniere = [], "", time.time(), True
        while True:
            if time.time() - debut > timeout:
                proc.kill()
                journal(f"délai dépassé ({timeout} s), one-off arrêté")
                break
            prets, _, _ = select.select([maitre], [], [], 1)
            if prets:
                try:
                    bloc = os.read(maitre, 65536)
                except OSError:
                    break
                if not bloc:
                    break
                reste += bloc.decode("utf-8", errors="replace").replace("\r", "")
                *completes, reste = reste.split("\n")
                for ligne in completes:
                    ligne = ANSI.sub("", ligne)
                    # Le message d'accueil du one-off n'apporte rien.
                    if banniere and not ligne.startswith("conteneur prêt"):
                        continue
                    banniere = False
                    lignes.append(ligne)
                    if ligne not in (MARQUE_DEBUT, MARQUE_FIN) and not (
                        lignes and MARQUE_DEBUT in lignes and MARQUE_FIN not in lignes
                    ):
                        journal(ligne)
            elif proc.poll() is not None:
                break
        os.close(maitre)
        proc.wait()
        if reste.strip():
            lignes.append(ANSI.sub("", reste))
        return lire_resultat(lignes), proc.returncode


def redemarrer_web(region, app, journal):
    """Les caches de référentiels sont propres à chaque process web : sans
    redémarrage, le site continuerait de servir l'ancienne valeur."""
    p = subprocess.run(
        ["scalingo", "--region", region, "--app", app, "restart", "web"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    sortie = ANSI.sub("", (p.stdout + p.stderr)).strip().splitlines()
    sortie = [s for s in sortie if "out-of-date" not in s and "Please update" not in s]
    journal("redémarrage web : " + (sortie[-1] if sortie else f"code {p.returncode}"))


# ─── Archive : état d'avant et restauration ──────────────────────────────


def etat_avant(releves, cible, operations):
    """Contenu de chaque objet cible AVANT la copie, tel que relevé.

    Archivé avec la tâche : c'est ce qui permet de revenir en arrière soi-même
    (bouton « Restaurer l'état d'avant ») et d'enquêter après coup. None pour
    un objet qui n'existait pas encore dans la cible.
    """
    tgt = releves.get(cible) or {}
    textes = tgt.get("contenus", {})
    out = []
    for op in operations:
        famille, cle = op["famille"], op["cle"]
        entree = {"famille": famille, "cle": cle, "etat": None}
        if famille == "arbre":
            v = _arbre_actif(tgt, cle) if tgt else None
            if v and v.get("texte_logique") in textes:
                logique = json.loads(textes[v["texte_logique"]])
                entree["etat"] = {
                    "sha": v["sha"],
                    "pk": v["pk"],
                    "nom": v["nom"],
                    "config": logique["config"],
                    "contenu": logique["contenu"],
                    "yaml": textes.get(v.get("texte_yaml"), ""),
                    "date_origine": _date_arbre(v),
                }
        else:
            o = tgt.get("familles", {}).get(famille, {}).get("objets", {}).get(cle)
            if o and o.get("texte") in textes:
                entree["etat"] = {
                    "sha": o["sha"],
                    "pk": o.get("pk"),
                    "facettes": o["facettes"],
                    "champs": json.loads(textes[o["texte"]]),
                    "date_origine": render.date_auteur(o.get("dates", []))[0],
                }
        out.append(entree)
    return out


def lot_restauration(avant, releves, ref, cible, mode, auteur):
    """Lot qui remet dans la cible le contenu archivé avant une copie.

    L'empreinte attendue de la cible est celle du dernier relevé : si
    quelqu'un a modifié l'objet depuis, apply_lot refuse, comme pour une copie.
    """
    tgt = releves.get(cible) or {}
    ops = []
    for entree in avant:
        e = entree.get("etat")
        if not e:
            continue
        famille, cle = entree["famille"], entree["cle"]
        if famille == "arbre":
            t = _arbre_actif(tgt, cle) if tgt else None
            ops.append(
                {
                    "famille": famille,
                    "cle": cle,
                    "sha_source": e["sha"],
                    "sha_cible_attendu": t and t["sha"],
                    "config": e["config"],
                    "contenu": e["contenu"],
                    "yaml": e.get("yaml") or "",
                    "nom_source": e.get("nom") or cle,
                    "date_origine": e.get("date_origine"),
                }
            )
        else:
            t = tgt.get("familles", {}).get(famille, {}).get("objets", {}).get(cle)
            ops.append(
                {
                    "famille": famille,
                    "cle": cle,
                    "sha_source": e["sha"],
                    "facettes_source": e.get("facettes"),
                    "sha_cible_attendu": t and t["sha"],
                    "champs": e["champs"],
                    "date_origine": e.get("date_origine"),
                }
            )
    # « archive » comme source : un seul mot, lu tel quel par le relevé.
    return {
        "ref": ref,
        "source": "archive",
        "cible": cible,
        "mode": mode,
        "auteur": auteur,
        "operations": ops,
    }
