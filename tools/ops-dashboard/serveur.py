"""Serveur local du tableau de bord : page, API, file d'attente FIFO des tâches.

Écoute sur 127.0.0.1 seulement. Les requêtes d'écriture exigent le jeton tiré
au démarrage (glissé dans la page) et un en-tête Host local : une autre page
ouverte dans le navigateur ne peut pas déclencher de transfert.

Une seule tâche tourne à la fois (worker unique, FIFO). Deux types :
- relevé : relit un ou plusieurs envs, met à jour l'index et le journal des
  changements (ce qui a bougé depuis le relevé précédent) ;
- transfert : applique un paquet d'opérations sur UN env cible, puis relit cet
  env : la page voit le nouvel état quand la tâche sort de la file.
"""

import collections
import datetime
import http.server
import json
import secrets
import threading
import time
import traceback
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import executeur
import render

ICI = Path(__file__).resolve().parent
MAX_JOURNAL = 300


def maintenant():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class Etat:
    def __init__(
        self,
        ordre,
        envs,
        politique,
        releves,
        relever,
        enregistrer,
        cache,
        resumeur,
        conteneur,
        auteur,
        archive=None,
    ):
        self.ordre = ordre
        self.envs = envs
        self.politique = politique
        self.releves = releves
        self.relever = relever
        self.enregistrer = enregistrer
        self.cache = cache
        self.resumeur = resumeur
        self.conteneur = conteneur
        self.auteur = auteur
        self.verrou = threading.RLock()
        self.cv = threading.Condition(self.verrou)
        self.version = 1
        self.version_taches = 1
        self.echecs = {}
        self._donnees = None
        self.taches = {}
        self.ordre_taches = []
        self.file = collections.deque()
        # Numérotation continue d'un démarrage à l'autre : une référence de
        # tâche (T-0012) reste unique dans le journal et les journaux admin.
        self.fichier_compteur = cache / "compteur_taches"
        try:
            self.compteur = int(self.fichier_compteur.read_text())
        except (OSError, ValueError):
            self.compteur = 100
        self.jeton = secrets.token_urlsafe(24)
        try:
            self.journal = json.loads((cache / "journal.json").read_text())
        except (OSError, ValueError):
            self.journal = []
        # Archive durable des tâches (hors cache) : lot exact, logs, résultat
        # et état des objets cibles AVANT chaque copie. Relue au démarrage.
        self.archive = Path(archive) if archive else cache / "archive"
        for sous in ("taches", "lots"):
            (self.archive / sous).mkdir(parents=True, exist_ok=True)
        self._charger_archive()

    # ─── archive ────────────────────────────────────────────────────────
    def _charger_archive(self):
        fichiers = sorted(
            (self.archive / "taches").glob("T-*.json"),
            key=lambda f: int(f.stem.split("-")[1]),
        )
        for f in fichiers:
            try:
                t = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            if t.get("statut") in ("en_cours", "en_attente"):
                # Le serveur s'est arrêté pendant la tâche : on ne sait pas si
                # elle a écrit. Il faut regarder la cible.
                t["statut"] = "interrompue"
                t["logs"].append(
                    [
                        time.time(),
                        "serveur arrêté pendant la tâche : état de la cible à vérifier",
                    ]
                )
                self._ecrire_tache(t)
            self.taches[t["id"]] = t
            self.ordre_taches.append(t["id"])
            self.compteur = max(self.compteur, int(t["id"].split("-")[1]))

    def _ecrire_tache(self, t):
        try:
            chemin = self.archive / "taches" / f"{t['id']}.json"
            tmp = chemin.with_suffix(".tmp")
            tmp.write_text(json.dumps(t, ensure_ascii=False, indent=1))
            tmp.replace(chemin)
        except OSError:
            pass

    def archiver(self, t, evenement):
        """Écrit la tâche entière + une ligne dans le journal d'actions (ajout seul)."""
        with self.verrou:
            self._ecrire_tache(t)
            ligne = {
                "quand": maintenant(),
                "evenement": evenement,
                "tache": t["id"],
                "type": t["type"],
                "statut": t["statut"],
                "libelle": t["libelle"],
                "source": t.get("source"),
                "cible": t.get("cible"),
                "mode": t.get("mode"),
                "operations": [
                    {"famille": o["famille"], "cle": o["cle"]}
                    for o in t.get("operations", [])
                ],
                "resultat": (t.get("resultat") or {}).get("statut"),
                "restaure": t.get("restaure"),
            }
            try:
                with open(self.archive / "actions.jsonl", "a") as f:
                    f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
            except OSError:
                pass

    # ─── données ────────────────────────────────────────────────────────
    def donnees(self):
        with self.verrou:
            if self._donnees and self._donnees[0] == self.version:
                data = self._donnees[1]
            else:
                data = render.construire(self.releves, self.echecs, self.ordre)
                self._donnees = (self.version, data)
                self._demander_resumes(data)
            return dict(
                data,
                resumes=self.resumeur.etat(),
                journal=self.journal[-80:],
                politique=self.politique,
            )

    def _demander_resumes(self, data):
        for fam in data["familles"]:
            for ligne in fam["lignes"]:
                for r in ligne.get("resumes", []):
                    self.resumeur.demander(
                        r["cle"],
                        r["objet"],
                        r["libelle_ancien"],
                        r["libelle_nouveau"],
                        data["textes"].get(r["ancien"]),
                        data["textes"].get(r["nouveau"]),
                    )

    def etat_leger(self):
        with self.verrou:
            return {
                "version": self.version,
                "version_taches": self.version_taches,
                "version_resumes": self.resumeur.version,
                "taches": [
                    self._resume_tache(self.taches[t]) for t in self.ordre_taches[-80:]
                ],
            }

    def tache(self, tid):
        with self.verrou:
            t = self.taches.get(tid)
            return json.loads(json.dumps(t)) if t else None

    @staticmethod
    def _resume_tache(t):
        return {k: v for k, v in t.items() if k != "logs"} | {"n_logs": len(t["logs"])}

    # ─── file d'attente ─────────────────────────────────────────────────
    def nouvelle_tache(
        self,
        type_,
        libelle,
        cible=None,
        operations=None,
        envs=None,
        source=None,
        mode=None,
        **extra,
    ):
        with self.cv:
            self.compteur += 1
            try:
                self.fichier_compteur.write_text(str(self.compteur))
            except OSError:
                pass
            t = {
                "id": f"T-{self.compteur:04d}",
                "type": type_,
                "libelle": libelle,
                "cible": cible,
                "source": source,
                "mode": mode,
                "envs": envs or ([cible] if cible else []),
                "operations": operations or [],
                "statut": "en_attente",
                "cree": maintenant(),
                "debut": None,
                "fin": None,
                "resultat": None,
                "logs": [],
                **extra,
            }
            self.taches[t["id"]] = t
            self.ordre_taches.append(t["id"])
            self.file.append(t["id"])
            self.version_taches += 1
            self.cv.notify()
        self.archiver(t, "creation")
        return t

    def annuler(self, tid):
        with self.cv:
            t = self.taches.get(tid)
            if not t or t["statut"] != "en_attente":
                return False
            self.file.remove(tid)
            t["statut"] = "annulee"
            t["fin"] = maintenant()
            self.version_taches += 1
            return True

    def journaliser(self, t, texte):
        with self.verrou:
            t["logs"].append([time.time(), texte])
            self.version_taches += 1

    def boucle(self):
        while True:
            with self.cv:
                while not self.file:
                    self.cv.wait()
                t = self.taches[self.file.popleft()]
                t["statut"] = "en_cours"
                t["debut"] = maintenant()
                self.version_taches += 1
            self.archiver(t, "debut")
            try:
                if t["type"] == "releve":
                    ok = self._releve(t, t["envs"])
                elif t["type"] == "restauration":
                    ok = self._restauration(t)
                else:
                    ok = self._transfert(t)
                statut = "ok" if ok else "echec"
            except Exception as e:  # noqa: BLE001 - la file ne doit jamais mourir
                self.journaliser(t, f"ERREUR inattendue : {e!r}")
                for ligne in traceback.format_exc().splitlines()[-6:]:
                    self.journaliser(t, ligne)
                statut = "echec"
            with self.verrou:
                t["statut"] = statut
                t["fin"] = maintenant()
                self.version_taches += 1
            self.archiver(t, "fin")

    # ─── relevé ─────────────────────────────────────────────────────────
    def _releve(self, t, envs, tache_cause=None):
        resultats = {}

        def un(env):
            try:
                self.journaliser(t, f"{env} : relevé en cours")
                data = self.relever(env)
                self.enregistrer(env, data)
                resultats[env] = data
                self.journaliser(t, f"{env} : ok en {data['duree_s']} s")
                for e in data.get("erreurs", []):
                    self.journaliser(
                        t,
                        f"{env} : famille {e['famille']} en erreur : {e['erreur'][:200]}",
                    )
            except Exception as e:  # noqa: BLE001
                with self.verrou:
                    self.echecs[env] = str(e)[:600]
                self.journaliser(t, f"{env} : ÉCHEC {str(e)[:400]}")

        fils = [threading.Thread(target=un, args=(e,)) for e in envs]
        for f in fils:
            f.start()
        for f in fils:
            f.join()
        with self.verrou:
            nouveaux = []
            for env, data in resultats.items():
                ancien = self.releves.get(env)
                self.releves[env] = data
                self.echecs.pop(env, None)
                if ancien and ancien.get("schema") == data.get("schema"):
                    nouveaux += self._changements(
                        env, ancien, data, tache_cause or t["id"]
                    )
                elif ancien:
                    self.journaliser(
                        t, f"{env} : format du relevé changé, pas de journal cette fois"
                    )
            if nouveaux:
                self.journal = (self.journal + nouveaux)[-MAX_JOURNAL:]
                try:
                    (self.cache / "journal.json").write_text(
                        json.dumps(self.journal, ensure_ascii=False)
                    )
                except OSError:
                    pass
            if resultats:
                self.version += 1
        if nouveaux:
            self.journaliser(
                t, f"{len(nouveaux)} changement(s) depuis le relevé précédent"
            )
        return len(resultats) == len(envs)

    def _changements(self, env, ancien, nouveau, tache):
        """Objets dont l'empreinte a changé entre deux relevés d'un env."""
        out = []
        quand = nouveau.get("releve_le")
        textes = dict(ancien.get("contenus", {}))
        textes.update(nouveau.get("contenus", {}))

        def ev(
            famille,
            cle,
            libelle,
            avant,
            apres,
            t_avant,
            t_apres,
            nature,
            par=None,
            date=None,
        ):
            if avant == apres:
                return
            e = {
                "quand": quand,
                "env": env,
                "famille": famille,
                "cle": cle,
                "libelle": libelle,
                "type": (
                    "apparu" if not avant else "disparu" if not apres else "modifié"
                ),
                "sha_avant": avant,
                "sha_apres": apres,
                "par": par,
                "date": date,
                "tache": tache,
            }
            if t_avant and t_apres and t_avant != t_apres:
                e["resume"] = render.cle_resume(nature, t_avant, t_apres)
                self.resumeur.demander(
                    e["resume"],
                    f"{famille} {cle} en {env}",
                    "relevé précédent",
                    "relevé actuel",
                    textes.get(t_avant),
                    textes.get(t_apres),
                )
            out.append(e)

        def actifs(r):
            return {
                v["cle"]: v
                for v in r["familles"].get("arbre", {}).get("versions", [])
                if v["statut"] == "active"
            }

        a, n = actifs(ancien), actifs(nouveau)
        for cle in sorted(set(a) | set(n)):
            va, vn = a.get(cle), n.get(cle)
            nature = "logique"
            if va and vn and va.get("texte_logique") == vn.get("texte_logique"):
                nature = "yaml"
            ev(
                "arbre",
                cle,
                (vn or va)["nom"],
                va and va["sha"],
                vn and vn["sha"],
                va and va.get("texte_" + nature),
                vn and vn.get("texte_" + nature),
                nature,
                par=vn and (vn.get("derniere_revision") or {}).get("par"),
                date=vn and vn.get("active_le"),
            )
        for famille, fam in nouveau["familles"].items():
            if famille == "arbre":
                continue
            oa = ancien["familles"].get(famille, {}).get("objets", {})
            on = fam.get("objets", {})
            for cle in sorted(set(oa) | set(on)):
                xa, xn = oa.get(cle), on.get(cle)
                dern = sorted(
                    (xn or {}).get("dates", []), key=lambda d: d.get("date") or ""
                )[-1:] or [{}]
                ev(
                    famille,
                    cle,
                    (xn or xa).get("libelle", ""),
                    xa and xa["sha"],
                    xn and xn["sha"],
                    xa and xa["texte"],
                    xn and xn["texte"],
                    "contenu",
                    par=dern[0].get("par"),
                    date=dern[0].get("date"),
                )
        return out

    # ─── transfert ──────────────────────────────────────────────────────
    def _transfert(self, t):
        cible, source = t["cible"], t["source"]
        with self.verrou:
            lot = executeur.construire_lot(
                self.releves,
                t["id"],
                source,
                cible,
                t["operations"],
                t["mode"],
                self.auteur,
            )
            avant = executeur.etat_avant(self.releves, cible, t["operations"])
        self._archiver_lot(t, lot, avant)
        self.journaliser(
            t,
            f"lot {t['id']} : {len(lot['operations'])} opération(s) {source or 'suppression'} → {cible}, "
            f"mode {'réel' if t['mode'] == 'reel' else 'simulation'} ; état d'avant archivé",
        )
        return self._executer_lot(t, lot)

    def _restauration(self, t):
        origine = t["restaure"]
        try:
            archive = json.loads(
                (self.archive / "lots" / f"{origine}.json").read_text()
            )
        except (OSError, ValueError):
            self.journaliser(
                t, f"archive du lot {origine} introuvable : rien à restaurer"
            )
            return False
        cible = t["cible"]
        with self.verrou:
            lot = executeur.lot_restauration(
                archive["avant"], self.releves, t["id"], cible, t["mode"], self.auteur
            )
            avant = executeur.etat_avant(self.releves, cible, t["operations"])
        absents = [e["cle"] for e in archive["avant"] if not e.get("etat")]
        if absents:
            self.journaliser(
                t,
                f"n'existaient pas avant {origine}, laissés tels quels (pas de suppression) : {', '.join(absents)}",
            )
        if not lot["operations"]:
            self.journaliser(t, "aucun objet à restaurer")
            return False
        self._archiver_lot(t, lot, avant)
        self.journaliser(
            t,
            f"restauration de l'état d'avant {origine} : {len(lot['operations'])} objet(s) dans {cible}, "
            f"mode {'réel' if t['mode'] == 'reel' else 'simulation'} ; état actuel archivé",
        )
        return self._executer_lot(t, lot)

    def _archiver_lot(self, t, lot, avant):
        try:
            (self.archive / "lots" / f"{t['id']}.json").write_text(
                json.dumps({"lot": lot, "avant": avant}, ensure_ascii=False)
            )
        except OSError as e:
            self.journaliser(t, f"ATTENTION : archive du lot impossible ({e})")
            return
        with self.verrou:
            t["avant_archive"] = any(e.get("etat") for e in avant)
        self.archiver(t, "lot_archive")

    def _executer_lot(self, t, lot):
        cible = t["cible"]
        cfg = self.envs[cible]
        if cfg["type"] == "docker":
            res, rc = executeur.executer_local(
                self.conteneur, lot, lambda x: self.journaliser(t, x)
            )
        else:
            res, rc = executeur.executer_scalingo(
                cfg["region"], cfg["app"], lot, lambda x: self.journaliser(t, x)
            )
        with self.verrou:
            t["resultat"] = res
        if not res:
            self.journaliser(
                t,
                f"pas de résultat lisible (code {rc}) : état de la cible inconnu, relevé de contrôle",
            )
            self._releve(t, [cible])
            return False
        self.journaliser(t, f"résultat : {res['statut']}")
        if res["statut"] == "applique":
            if cfg["type"] == "scalingo":
                executeur.redemarrer_web(
                    cfg["region"], cfg["app"], lambda x: self.journaliser(t, x)
                )
            else:
                self.journaliser(
                    t,
                    f"cache du site local : redémarrer {self.conteneur} pour voir le changement dans le simulateur",
                )
            self.journaliser(t, f"relevé de {cible} pour afficher le nouvel état")
            self._releve(t, [cible])
        return res["statut"] in ("applique", "simule")


TYPES = {
    ".css": "text/css; charset=utf-8",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}


class Gestionnaire(http.server.BaseHTTPRequestHandler):
    etat: Etat = None
    port = 0
    rendeur = None
    # Feuilles de style servies telles quelles depuis le dépôt local, pour que
    # le rendu des contenus riches ait l'apparence du site (DSFR + calendrier).
    statiques = {}

    def log_message(self, *args):
        pass

    def _hote_ok(self):
        return self.headers.get("Host") in (
            f"127.0.0.1:{self.port}",
            f"localhost:{self.port}",
        )

    def _json(self, code, obj):
        corps = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def do_GET(self):
        if not self._hote_ok():
            return self._json(403, {"erreur": "hôte refusé"})
        chemin = urlparse(self.path).path
        if chemin == "/":
            data = self.etat.donnees()
            gabarit = (ICI / "template.html").read_text()
            meta = {"servi": True, "jeton": self.etat.jeton}
            js = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
            html = gabarit.replace("/*__DONNEES__*/null", js).replace(
                "/*__META__*/null", json.dumps(meta)
            )
            corps = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(corps)))
            self.end_headers()
            self.wfile.write(corps)
        elif chemin == "/api/donnees":
            self._json(200, self.etat.donnees())
        elif chemin == "/api/etat":
            self._json(200, self.etat.etat_leger())
        elif chemin == "/api/resumes":
            self._json(200, self.etat.resumeur.etat())
        elif chemin == "/api/rendu":
            self._rendu(parse_qs(urlparse(self.path).query))
        elif chemin.startswith("/statique/"):
            self._statique(chemin[len("/statique/") :])  # noqa: E203
        elif chemin.startswith("/api/taches/"):
            t = self.etat.tache(chemin.rsplit("/", 1)[1])
            self._json(200, t) if t else self._json(404, {"erreur": "tâche inconnue"})
        else:
            self._json(404, {"erreur": "inconnu"})

    def _rendu(self, q):
        import rendu

        famille, cle = (q.get("famille") or [""])[0], (q.get("cle") or [""])[0]
        if famille not in ("pc", "contenu"):
            return self._json(
                400, {"erreur": "rendu disponible pour les PC et les contenus"}
            )
        with self.etat.verrou:
            sortie, items = rendu.items_pour_ligne(self.etat.releves, famille, cle)
        try:
            rendus = self.rendeur.rendre(items)
        except Exception as e:  # noqa: BLE001
            return self._json(500, {"erreur": str(e)[:500]})
        for v in sortie.values():
            v["blocs"] = rendus.get(v["cle_rendu"]) or []
        self._json(200, sortie)

    def _statique(self, chemin):
        racine, _, reste = chemin.partition("/")
        base = self.statiques.get(racine)
        if base is None:
            return self._json(404, {"erreur": "inconnu"})
        fichier = (base / reste).resolve() if reste else base
        if not str(fichier).startswith(str(base.resolve())) or not fichier.is_file():
            return self._json(404, {"erreur": "inconnu"})
        corps = fichier.read_bytes()
        self.send_response(200)
        self.send_header(
            "Content-Type", TYPES.get(fichier.suffix, "application/octet-stream")
        )
        self.send_header("Cache-Control", "max-age=3600")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def do_POST(self):
        if not self._hote_ok() or self.headers.get("X-Jeton") != self.etat.jeton:
            return self._json(403, {"erreur": "jeton ou hôte refusé"})
        chemin = urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        try:
            corps = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._json(400, {"erreur": "JSON invalide"})
        if chemin == "/api/releve":
            envs = [
                e for e in corps.get("envs", self.etat.ordre) if e in self.etat.envs
            ]
            t = self.etat.nouvelle_tache(
                "releve", f"relevé {', '.join(envs)}", envs=envs
            )
            return self._json(200, {"taches": [t["id"]]})
        if chemin == "/api/transferts":
            try:
                ids = creer_transferts(self.etat, corps.get("operations", []))
            except ValueError as e:
                return self._json(400, {"erreur": str(e)})
            return self._json(200, {"taches": ids})
        if chemin.startswith("/api/taches/") and chemin.endswith("/restaurer"):
            try:
                t = creer_restauration(self.etat, chemin.split("/")[3])
            except ValueError as e:
                return self._json(400, {"erreur": str(e)})
            return self._json(200, {"taches": [t["id"]]})
        if chemin.startswith("/api/taches/") and chemin.endswith("/annuler"):
            ok = self.etat.annuler(chemin.split("/")[3])
            return self._json(200 if ok else 409, {"annulee": ok})
        self._json(404, {"erreur": "inconnu"})


FAMILLES_CONNUES = {f[0] for f in render.FAMILLES}


def creer_transferts(etat, operations):
    """Valide les opérations et crée une tâche par couple (source, cible).

    Une opération est une copie (source -> cible) ou une suppression
    (`action: "supprimer"`) : propager l'absence d'un objet, la source
    facultative étant l'env où il a déjà disparu.
    """
    if not operations:
        raise ValueError("aucune opération")
    groupes = collections.OrderedDict()
    vues = set()

    def present(releve, famille, cle):
        if not releve:
            return False
        if famille == "arbre":
            return executeur._arbre_actif(releve, cle) is not None
        return cle in releve["familles"].get(famille, {}).get("objets", {})

    with etat.verrou:
        for op in operations:
            famille, cle, source, cible = (
                op.get("famille"),
                op.get("cle"),
                op.get("source"),
                op.get("cible"),
            )
            suppression = op.get("action") == "supprimer"
            if famille not in FAMILLES_CONNUES:
                raise ValueError(f"famille inconnue : {famille}")
            if (
                cible not in etat.envs
                or (source is not None and source not in etat.envs)
                or source == cible
            ):
                raise ValueError(
                    f"{cle} : couple source/cible invalide ({source} → {cible})"
                )
            if source is None and not suppression:
                raise ValueError(f"{cle} : une copie demande une source")
            mode = etat.politique.get(cible)
            if not mode:
                raise ValueError(f"{cle} : écriture vers {cible} désactivée")
            if (famille, cle, cible) in vues:
                raise ValueError(f"{cle} : deux opérations vers {cible}")
            vues.add((famille, cle, cible))
            if source is not None and not etat.releves.get(source):
                raise ValueError(f"pas de relevé pour {source}")
            if suppression:
                if not present(etat.releves.get(cible), famille, cle):
                    raise ValueError(f"{cle} : déjà absent de {cible}")
                if source is not None and present(
                    etat.releves.get(source), famille, cle
                ):
                    raise ValueError(
                        f"{cle} : présent en {source}, ce n'est pas une absence à propager"
                    )
            elif not present(etat.releves.get(source), famille, cle):
                raise ValueError(f"{cle} absent de {source}")
            o = {"famille": famille, "cle": cle}
            if suppression:
                o["action"] = "supprimer"
            groupes.setdefault((source, cible), []).append(o)
    ids = []
    for (source, cible), ops in groupes.items():
        noms = ", ".join(
            ("✕ " if o.get("action") else "") + o["cle"] for o in ops[:4]
        ) + (f" +{len(ops) - 4}" if len(ops) > 4 else "")
        if all(o.get("action") == "supprimer" for o in ops):
            libelle = f"{noms} : supprimé de {cible}" + (
                f" (absent de {source})" if source else ""
            )
        else:
            libelle = f"{noms} : {source} → {cible}"
        t = etat.nouvelle_tache(
            "transfert",
            libelle,
            cible=cible,
            source=source,
            operations=[dict(o, source=source, cible=cible) for o in ops],
            mode=etat.politique[cible],
        )
        ids.append(t["id"])
    return ids


def creer_restauration(etat, tid):
    """Tâche qui remet dans la cible l'état archivé avant la tâche `tid`."""
    with etat.verrou:
        t = etat.taches.get(tid)
    if not t or t["type"] not in ("transfert", "restauration"):
        raise ValueError(f"{tid} : pas une copie")
    if not t.get("avant_archive"):
        raise ValueError(f"{tid} : pas d'état d'avant archivé")
    mode = etat.politique.get(t["cible"])
    if not mode:
        raise ValueError(f"écriture vers {t['cible']} désactivée")
    noms = ", ".join(o["cle"] for o in t["operations"][:4]) + (
        f" +{len(t['operations']) - 4}" if len(t["operations"]) > 4 else ""
    )
    return etat.nouvelle_tache(
        "restauration",
        f"↶ {noms} : état d'avant {tid} → {t['cible']}",
        cible=t["cible"],
        source="archive",
        operations=[dict(o, source="archive") for o in t["operations"]],
        mode=mode,
        restaure=tid,
    )


def servir(etat, port, depot=None):
    import rendu

    Gestionnaire.etat = etat
    Gestionnaire.rendeur = rendu.Rendeur(etat.conteneur)
    if depot:
        Gestionnaire.statiques = {
            "dsfr": depot / "node_modules/@gouvfr/dsfr/dist",
            "nitrates": depot / "envergo/static/nitrates",
        }
    for p in range(port, port + 20):
        try:
            httpd = http.server.ThreadingHTTPServer(("127.0.0.1", p), Gestionnaire)
            Gestionnaire.port = p
            break
        except OSError:
            continue
    else:
        raise SystemExit(f"aucun port libre entre {port} et {port + 19}")
    threading.Thread(target=etat.boucle, daemon=True, name="file").start()
    return httpd, Gestionnaire.port
