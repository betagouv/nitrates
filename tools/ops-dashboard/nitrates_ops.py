#!/usr/bin/env python3
"""Tableau de bord ops nitrates : compare les objets éditables des 4 environnements.

    tools/ops-dashboard/nitrates-ops                  # serveur local : relève les 4 envs, ouvre la page
    tools/ops-dashboard/nitrates-ops --envs local     # serveur, relevé initial de local seulement
    tools/ops-dashboard/nitrates-ops --render-only    # page statique depuis les derniers relevés

Lecture seule partout. Les environnements Scalingo sont lus par un tunnel
`scalingo db-tunnel` ouvert le temps du relevé, la requête tourne dans le
conteneur Django local (`envergo_django` par défaut) avec une session Postgres en
lecture seule. Il faut SCALINGO_API_TOKEN dans l'environnement : le wrapper
`nitrates-ops` passe par `secret exec beta` (un seul TouchID pour tout).

Les relevés et la page générée restent sur le poste, hors dépôt :
~/.cache/nitrates-ops/ (ils contiennent des données de prod).
"""

import argparse
import datetime
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))

import render  # noqa: E402

ENVS = {
    "local": {"type": "docker"},
    "dev": {
        "type": "scalingo",
        "region": "osc-fr1",
        "app": "nitrates-dev",
        "port": 10431,
        "url": "https://nitrates-dev.osc-fr1.scalingo.io",
    },
    "staging": {
        "type": "scalingo",
        "region": "osc-fr1",
        "app": "nitrates-staging",
        "port": 10432,
        "url": "https://nitrates-staging.osc-fr1.scalingo.io",
    },
    "prod": {
        "type": "scalingo",
        "region": "osc-secnum-fr1",
        "app": "nitrates-prod",
        "port": 10433,
        "url": "https://nitrates.beta.gouv.fr",
    },
}
ORDRE = ["local", "dev", "staging", "prod"]

CONTENEUR = os.environ.get("NITRATES_OPS_CONTENEUR", "envergo_django")
URL_LOCALE = os.environ.get("NITRATES_OPS_URL_LOCALE", "http://localhost:8000")
DEPOT_LOCAL = Path(
    # Dépôt monté dans le conteneur local (git du code local, CSS DSFR pour le
    # rendu riche). Par défaut : le dépôt qui contient cet outil.
    os.environ.get("NITRATES_OPS_DEPOT_LOCAL", str(ICI.parents[1]))
).expanduser()
CLE_SSH = Path(os.environ.get("NITRATES_OPS_CLE_SSH", "~/.ssh/id_rsa")).expanduser()
CACHE = Path(os.environ.get("NITRATES_OPS_CACHE", "~/.cache/nitrates-ops")).expanduser()
# Archive des actions (copies, restaurations, relevés) : durable, hors cache.
ARCHIVE = Path(
    os.environ.get("NITRATES_OPS_ARCHIVE", "~/.local/state/nitrates-ops/archive")
).expanduser()

# Le script de relevé est envoyé sur stdin du conteneur, précédé du DSN : le
# mot de passe de la base n'apparaît ainsi dans aucune ligne de commande.
AMORCE = (
    "import sys;d=sys.stdin.readline().strip();s=sys.stdin.read();"
    "exec(compile(s,'collect_snapshot.py','exec'),{'__name__':'__main__','OPS_DSN':d})"
)


def log(env, msg):
    print(f"[{env:>7}] {msg}", file=sys.stderr, flush=True)


def masquer(txt):
    """Retire tout ce qui ressemble à une URL avec identifiants."""
    return re.sub(r"[a-z+]+://[^\s'\"]+", "<url masquée>", txt or "")


def scalingo(env, *args, timeout=60):
    cfg = ENVS[env]
    return subprocess.run(
        ["scalingo", "--region", cfg["region"], "--app", cfg["app"], *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        stdin=subprocess.DEVNULL,
    )


def lancer_releve(dsn):
    source = (ICI / "collect_snapshot.py").read_text()
    p = subprocess.run(
        ["docker", "exec", "-i", CONTENEUR, "python", "-c", AMORCE],
        input=(dsn or "") + "\n" + source,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if p.returncode != 0:
        raise RuntimeError(
            masquer(p.stderr.strip())[-1500:] or f"code retour {p.returncode}"
        )
    return json.loads(p.stdout)


def code_local():
    def git(*a):
        return subprocess.run(
            ["git", "-C", str(DEPOT_LOCAL), *a], capture_output=True, text=True
        ).stdout.strip()

    sale = bool(git("status", "--porcelain", "--untracked-files=no"))
    return {
        "ref": git("rev-parse", "--abbrev-ref", "HEAD"),
        "commit": git("rev-parse", "--short", "HEAD"),
        "modifs_non_commitees": sale,
    }


def code_scalingo(env):
    """Dernier déploiement réussi (ref git + date), au mieux."""
    p = scalingo(env, "deployments", timeout=60)
    for ligne in p.stdout.splitlines():
        if "success" not in ligne:
            continue
        # │ ID │ DATE │ DURATION │ USER │ GIT REF │ STATUS │ IMAGE SIZE │
        cols = [c.strip() for c in re.split(r"[│|]", ligne.strip())[1:-1]]
        if len(cols) >= 6:
            sha = cols[4]
            tags = subprocess.run(
                ["git", "-C", str(DEPOT_LOCAL), "tag", "--points-at", sha],
                capture_output=True,
                text=True,
            ).stdout.split()
            return {
                "deploye_le": cols[1],
                "par": cols[3],
                "ref": " ".join(tags) or "",
                "commit": sha[:9],
            }
    return {"brut": "déploiement illisible"}


def port_ouvert(port):
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def releve_scalingo(env):
    cfg = ENVS[env]
    if not os.environ.get("SCALINGO_API_TOKEN"):
        raise RuntimeError(
            "SCALINGO_API_TOKEN absent : lancer via tools/ops-dashboard/nitrates-ops (voir README)"
        )
    p = scalingo(env, "env")
    url = None
    admin = "admin/"
    for ligne in p.stdout.splitlines():
        if ligne.startswith("SCALINGO_POSTGRESQL_URL="):
            url = ligne.split("=", 1)[1].strip()
        elif ligne.startswith("DJANGO_ADMIN_URL="):
            admin = ligne.split("=", 1)[1].strip() or admin
    if not url:
        raise RuntimeError(
            "SCALINGO_POSTGRESQL_URL introuvable ("
            + masquer(p.stderr.strip())[:300]
            + ")"
        )
    port = cfg["port"]
    if port_ouvert(port):
        raise RuntimeError(f"port {port} déjà occupé (un ancien tunnel ?)")
    cmd = [
        "scalingo",
        "--region",
        cfg["region"],
        "--app",
        cfg["app"],
        "db-tunnel",
        "-p",
        str(port),
    ]
    if CLE_SSH.exists():
        cmd += ["-i", str(CLE_SSH)]
    tunnel = subprocess.Popen(
        cmd + ["SCALINGO_POSTGRESQL_URL"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
    )
    sortie = []
    threading.Thread(target=lambda: sortie.extend(tunnel.stdout), daemon=True).start()
    try:
        debut = time.time()
        while not port_ouvert(port):
            if tunnel.poll() is not None:
                raise RuntimeError(
                    "tunnel fermé : " + masquer("".join(sortie)).strip()[-600:]
                )
            if time.time() - debut > 45:
                raise RuntimeError(
                    "tunnel non ouvert après 45 s : "
                    + masquer("".join(sortie)).strip()[-600:]
                )
            time.sleep(0.5)
        log(env, f"tunnel ouvert en {time.time() - debut:.0f} s")
        u = urlsplit(url)
        identifiants = u.netloc.rsplit("@", 1)[0]
        dsn = urlunsplit(
            (
                u.scheme,
                f"{identifiants}@host.docker.internal:{port}",
                u.path,
                u.query,
                "",
            )
        )
        data = lancer_releve(dsn)
        # Liens directs vers l'admin de l'env (le préfixe admin est propre à
        # chaque env ; il reste dans le relevé local, jamais affiché ailleurs).
        data["liens"] = {"base": cfg["url"], "admin": admin.strip("/") + "/"}
        return data
    finally:
        tunnel.terminate()
        try:
            tunnel.wait(timeout=10)
        except subprocess.TimeoutExpired:
            tunnel.kill()


def relever(env):
    debut = time.time()
    if ENVS[env]["type"] == "docker":
        data = lancer_releve("")
        data["code"] = code_local()
        data["liens"] = {"base": URL_LOCALE, "admin": "admin/"}
    else:
        data = releve_scalingo(env)
        data["code"] = code_scalingo(env)
    data["env"] = env
    data["releve_le"] = datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds"
    )
    data["duree_s"] = round(time.time() - debut, 1)
    return data


def enregistrer(env, data):
    dossier = CACHE / "releves" / env
    dossier.mkdir(parents=True, exist_ok=True)
    horo = data["releve_le"].replace(":", "").replace("-", "")[:15]
    chemin = dossier / f"{horo}.json"
    chemin.write_text(json.dumps(data, ensure_ascii=False))
    (dossier / "dernier.json").write_text(json.dumps(data, ensure_ascii=False))
    # On garde les 30 derniers relevés par env, le reste part.
    anciens = sorted(p for p in dossier.glob("2*.json"))[:-30]
    for p in anciens:
        p.unlink()
    return chemin


def derniers_releves():
    out = {}
    for env in ORDRE:
        p = CACHE / "releves" / env / "dernier.json"
        if p.exists():
            out[env] = json.loads(p.read_text())
    return out


def auteur_git():
    """Comptes candidats pour signer les copies au journal admin des envs.

    Nom git puis début de l'e-mail git : les comptes Django diffèrent d'une base
    à l'autre (pseudo sur les envs Scalingo, e-mail en local), apply_lot essaie
    les deux. Surcharge : NITRATES_OPS_AUTEUR="compte1,compte2".
    """

    def git(cle):
        p = subprocess.run(["git", "config", cle], capture_output=True, text=True)
        return p.stdout.strip()

    return ",".join(x for x in (git("user.name"), git("user.email").split("@")[0]) if x)


def politique_ecriture():
    """Mode d'écriture par env cible : reel, simulation, ou absent (interdit).

    Défaut : local, dev et staging en réel (staging depuis le 15/10), prod
    interdite. Surcharge : NITRATES_OPS_ECRITURE="staging=simulation".
    """
    pol = {"local": "reel", "dev": "reel", "staging": "reel"}
    for item in os.environ.get("NITRATES_OPS_ECRITURE", "").split(","):
        env, _, mode = item.partition("=")
        if env.strip() in ENVS:
            if mode.strip() in ("reel", "simulation"):
                pol[env.strip()] = mode.strip()
            else:
                pol.pop(env.strip(), None)
    return pol


def servir(args, envs):
    import resumes
    import serveur

    CACHE.mkdir(parents=True, exist_ok=True)
    resumeur = resumes.Resumeur(CACHE / "resumes.json", actif=not args.sans_ia)
    etat = serveur.Etat(
        ORDRE,
        ENVS,
        politique_ecriture(),
        derniers_releves(),
        relever,
        enregistrer,
        CACHE,
        resumeur,
        CONTENEUR,
        os.environ.get("NITRATES_OPS_AUTEUR") or auteur_git(),
        ARCHIVE,
    )
    httpd, port = serveur.servir(etat, args.port, DEPOT_LOCAL)
    url = f"http://127.0.0.1:{port}/"
    print(f"Tableau de bord : {url}  (Ctrl-C pour arrêter)", flush=True)
    if envs:
        etat.nouvelle_tache("releve", f"relevé {', '.join(envs)}", envs=envs)
    if not args.no_open:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("arrêt", flush=True)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--envs",
        default=",".join(ORDRE),
        help="envs relevés au démarrage (défaut : les 4)",
    )
    ap.add_argument(
        "--port", type=int, default=int(os.environ.get("NITRATES_OPS_PORT", "8765"))
    )
    ap.add_argument(
        "--sans-ia",
        action="store_true",
        help="pas de résumé automatique des différences",
    )
    ap.add_argument("--no-open", action="store_true", help="n'ouvre pas le navigateur")
    ap.add_argument(
        "--render-only",
        action="store_true",
        help="page statique depuis les derniers relevés",
    )
    ap.add_argument(
        "--static",
        action="store_true",
        help="relève puis génère une page statique, sans serveur",
    )
    args = ap.parse_args()
    envs = [e.strip() for e in args.envs.split(",") if e.strip()]
    inconnus = [e for e in envs if e not in ENVS]
    if inconnus:
        ap.error(f"env inconnu : {', '.join(inconnus)}")

    if not args.render_only and not args.static:
        return servir(args, envs)

    if args.static:
        echecs = {}

        def tache(env):
            try:
                log(env, "relevé en cours")
                data = relever(env)
                chemin = enregistrer(env, data)
                log(env, f"ok en {data['duree_s']} s -> {chemin}")
            except Exception as e:  # noqa: BLE001
                echecs[env] = masquer(str(e))
                log(env, f"ÉCHEC : {echecs[env][:600]}")

        fils = [threading.Thread(target=tache, args=(e,)) for e in envs]
        for f in fils:
            f.start()
        for f in fils:
            f.join()
        (CACHE / "derniers_echecs.json").write_text(
            json.dumps(echecs, ensure_ascii=False)
        )

    releves = derniers_releves()
    if not releves:
        sys.exit("Aucun relevé disponible.")
    echecs_path = CACHE / "derniers_echecs.json"
    echecs = json.loads(echecs_path.read_text()) if echecs_path.exists() else {}
    page = CACHE / "tableau_de_bord.html"
    page.write_text(render.page(releves, echecs, ORDRE))
    print(str(page))
    if not args.no_open:
        webbrowser.open(page.as_uri())


if __name__ == "__main__":
    main()
