"""Compare les relevés des environnements et produit la page HTML autonome.

Pour chaque objet (clé naturelle), on regroupe les environnements par
empreinte. Chaque contenu distinct reçoit une lettre : A est la version
modifiée le plus récemment (d'après les dates connues), B la suivante, etc.
Même lettre = même contenu, octet pour octet.

Les signaux d'incohérence sont calculés ici, pas dans la page, pour qu'ils
restent testables.
"""

import datetime
import difflib
import hashlib
import itertools
import json
from pathlib import Path

ICI = Path(__file__).resolve().parent

AMONT = ["local", "dev", "staging", "prod"]  # sens normal de propagation

FAMILLES = [
    ("arbre", "Arbres de décision", "principal"),
    ("pc", "Codes de prescription (PC)", "principal"),
    ("contenu", "Contenus éditoriaux", "principal"),
    ("culture", "Cultures", "referentiel"),
    ("brancheculturale", "Branches culturales", "referentiel"),
    ("groupecultureui", "Groupes de cultures (UI)", "referentiel"),
    ("fertilisant", "Fertilisants", "referentiel"),
    ("notereglementaire", "Notes réglementaires", "referentiel"),
    ("evenementphenologique", "Événements phénologiques", "referentiel"),
    ("lienreference", "Liens de référence", "referentiel"),
    ("ouverture", "Ouverture des départements", "referentiel"),
    ("couleurzone", "Couleurs des zones", "referentiel"),
]

MAX_LIGNES_DIFF = 4000
POIDS = {"rouge": 100, "orange": 10, "info": 1}
# Empreinte d'un YAML brut vide.
SHA_VIDE = hashlib.sha256(b"").hexdigest()


def _dt(s):
    return datetime.datetime.fromisoformat(s) if s else None


def _court(s):
    d = _dt(s)
    return d.astimezone().strftime("%d/%m/%Y %H:%M") if d else "?"


MARGE_COPIE_S = 120


def date_auteur(traces):
    """Date d'écriture du contenu actuel, à partir des traces d'un objet.

    Une copie nitrates-ops n'écrit pas de contenu neuf : elle ne rajeunit pas
    la version. Elle remplace tout ce qui la précède (et le `updated_at` posé
    par sa propre sauvegarde, d'où la marge). On retient donc :
    - la trace la plus récente postérieure à la dernière copie, s'il y en a ;
    - sinon la date d'écriture d'origine portée par la copie (ou None) ;
    - sans copie, la trace la plus récente.

    Renvoie (date, trace retenue, copie éventuelle).
    """
    traces = [t for t in traces if t.get("date")]
    copies = [t for t in traces if t.get("copie")]
    copie = max(copies, key=lambda t: t["date"]) if copies else None
    autres = [t for t in traces if not t.get("copie")]
    if copie:
        limite = _dt(copie["date"]) + datetime.timedelta(seconds=MARGE_COPIE_S)
        apres = [t for t in autres if _dt(t["date"]) > limite]
        if apres:
            t = max(apres, key=lambda t: t["date"])
            return t["date"], t, None
        return copie["copie"].get("date_origine"), copie, copie
    if autres:
        t = max(autres, key=lambda t: t["date"])
        return t["date"], t, None
    return None, {}, None


def lettres(cellules):
    """Attribue A, B, C… aux empreintes distinctes, la plus récente d'abord."""
    par_sha = {}
    for env, c in cellules.items():
        if c and not c.get("absent"):
            v = par_sha.setdefault(
                c["sha"], {"sha": c["sha"], "envs": [], "date": None}
            )
            v["envs"].append(env)
            if c.get("date") and (v["date"] is None or c["date"] > v["date"]):
                v["date"] = c["date"]
                v["origine"] = {
                    "env": env,
                    "par": c.get("par"),
                    "source": c.get("date_source"),
                    "detail": c.get("detail"),
                }
    versions = sorted(
        par_sha.values(),
        key=lambda v: (v["date"] is not None, v["date"] or "", len(v["envs"])),
        reverse=True,
    )
    reference = _dt(versions[0]["date"]) if versions else None
    for i, v in enumerate(versions):
        v["lettre"] = chr(ord("A") + i)
        # Retard sur la version la plus récente, en jours : sert au dégradé
        # de couleur (proche = froid, loin = chaud). None si date inconnue.
        d = _dt(v["date"])
        v["retard_j"] = (
            round((reference - d).total_seconds() / 86400, 2)
            if reference and d
            else None
        )
        for env in v["envs"]:
            cellules[env]["version"] = v["lettre"]
            cellules[env]["retard_j"] = v["retard_j"]
    return versions


def nature_principale(ligne):
    """Texte comparé par défaut : la logique d'un arbre si elle diffère, sinon son YAML."""
    if ligne["famille"] != "arbre":
        return "contenu"
    logiques = {
        (c.get("textes") or {}).get("logique")
        for c in ligne["cellules"].values()
        if c and not c.get("absent")
    }
    return "logique" if len(logiques) > 1 else "yaml"


def cle_resume(nature, ancien, nouveau):
    return f"{nature}:{ancien}:{nouveau}"


def demandes_resumes(ligne, versions):
    """Un résumé par version plus ancienne que A, orienté ancienne -> A."""
    if len(versions) < 2:
        return []
    nature = nature_principale(ligne)
    texte_de = {}
    for v in versions:
        c = ligne["cellules"][v["envs"][0]]
        texte_de[v["lettre"]] = (c.get("textes") or {}).get(nature)
    out = []
    a = versions[0]
    for v in versions[1:]:
        ancien, nouveau = texte_de[v["lettre"]], texte_de[a["lettre"]]
        if not ancien or not nouveau or ancien == nouveau:
            continue
        out.append(
            {
                "cle": cle_resume(nature, ancien, nouveau),
                "nature": nature,
                "de": v["lettre"],
                "vers": a["lettre"],
                "ancien": ancien,
                "nouveau": nouveau,
                "objet": f"{ligne['famille']} {ligne['cle']}",
                "libelle_ancien": f"{v['lettre']} ({', '.join(v['envs'])})",
                "libelle_nouveau": f"{a['lettre']} ({', '.join(a['envs'])})",
            }
        )
    return out


def signaux_communs(cellules, versions, envs_releves):
    sig = []
    presents = [
        e
        for e in AMONT
        if e in envs_releves and cellules.get(e) and not cellules[e].get("absent")
    ]
    absents = [
        e for e in AMONT if e in envs_releves and (cellules.get(e) or {}).get("absent")
    ]
    if len(versions) > 1:
        sig.append(
            {
                "niveau": "orange",
                "code": "divergent",
                "texte": f"{len(versions)} versions différentes ("
                + ", ".join(f"{v['lettre']} : {'/'.join(v['envs'])}" for v in versions)
                + ")",
            }
        )
        if not any(v["date"] for v in versions):
            sig.append(
                {
                    "niveau": "info",
                    "code": "sans_date",
                    "texte": "Aucune trace de modification nulle part : "
                    "impossible de dire quelle version est la plus récente.",
                }
            )
    for e in presents:
        rang = AMONT.index(e)
        manquants = [u for u in AMONT[1:rang] if u in absents]
        if manquants:
            niveau = "rouge" if e == "prod" else "orange"
            sig.append(
                {
                    "niveau": niveau,
                    "code": "cree_en_aval",
                    "texte": f"Présent en {e} mais absent en {', '.join(manquants)} : "
                    "créé en aval sans passer par l'amont.",
                }
            )
    if presents and absents:
        attente = [
            e
            for e in absents
            if e != "local" and any(AMONT.index(p) < AMONT.index(e) for p in presents)
        ]
        if attente:
            sig.append(
                {
                    "niveau": "info",
                    "code": "en_attente",
                    "texte": f"Absent en {', '.join(attente)} (présent en amont : pas encore propagé).",
                }
            )
    st, pr = cellules.get("staging"), cellules.get("prod")
    if (
        st
        and pr
        and not st.get("absent")
        and not pr.get("absent")
        and st["sha"] != pr["sha"]
    ):
        sig.append(
            {
                "niveau": "rouge",
                "code": "prod_staging",
                "texte": "La prod diffère de staging : ce qui est en prod devrait être passé par staging.",
            }
        )
    # Une version aval modifiée APRÈS la version amont : une copie amont -> aval
    # écraserait ce travail (cas de l'incident PC du 09/09).
    # Si l'amont n'a aucune trace de modification, la date aval suffit : on ne
    # peut pas prouver que l'amont est plus récent (cas pc8 : édition juriste en
    # staging, dev resté sur l'ancien texte sans aucune trace).
    for u in ("dev", "staging"):
        cu = cellules.get(u)
        if not cu or cu.get("absent"):
            continue
        suivant = AMONT.index(u) + 1
        for d in AMONT[suivant:]:
            cd = cellules.get(d)
            if (
                not cd
                or cd.get("absent")
                or cd["sha"] == cu["sha"]
                or not cd.get("date")
            ):
                continue
            if cu.get("date") and cd["date"] <= cu["date"]:
                continue
            amont = (
                f"{u} ({_court(cu['date'])})"
                if cu.get("date")
                else f"{u} (aucune trace de modification)"
            )
            sig.append(
                {
                    "niveau": "orange",
                    "code": "aval_plus_recent",
                    "texte": f"Modifié en {d} ({_court(cd['date'])}) après {amont} : "
                    f"une copie {u} → {d} écraserait ce travail.",
                }
            )
    return sig


def diff(a, b):
    """Diff unifié de a vers b, sans les en-têtes de fichiers (la page les écrit)."""
    lignes = list(
        difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm="", n=3)
    )[2:]
    tronque = len(lignes) > MAX_LIGNES_DIFF
    return {
        "texte": "\n".join(lignes[:MAX_LIGNES_DIFF]),
        "tronque": tronque,
        "lignes": len(lignes),
    }


class Constructeur:
    def __init__(self, releves, ordre):
        self.releves = releves
        self.ordre = ordre
        self.envs_releves = [e for e in ordre if e in releves]
        self.textes = {}
        for r in releves.values():
            self.textes.update(r.get("contenus", {}))
        self.diffs = {}
        self.textes_utiles = set()

    def ajouter_diffs(self, ligne):
        """Un diff par paire de textes distincts, par nature de texte.

        Clé de paire = les deux empreintes de texte triées ; le diff va de la
        plus petite vers la plus grande, la page l'inverse au besoin. On
        compare donc environnement contre environnement, y compris quand
        seul le YAML brut diffère (même version logique).
        """
        par_nature = {}
        for c in ligne["cellules"].values():
            if c and not c.get("absent"):
                for nature, t in (c.get("textes") or {}).items():
                    if t:
                        par_nature.setdefault(nature, set()).add(t)
                        self.textes_utiles.add(t)
        for nature, shas in par_nature.items():
            for ta, tb in itertools.combinations(sorted(shas), 2):
                a, b = self.textes.get(ta), self.textes.get(tb)
                if a is None or b is None:
                    continue
                cle = f"{ligne['famille']}|{ligne['cle']}|{nature}|{ta[:12]}|{tb[:12]}"
                self.diffs[cle] = diff(a, b)
                ligne["diffs"].setdefault(nature, {})[f"{ta}|{tb}"] = cle

    # ─── arbres ─────────────────────────────────────────────────────────
    def arbres(self):
        par_env = {}
        index_sha = {}
        for env in self.envs_releves:
            fam = self.releves[env]["familles"].get("arbre")
            if not fam:
                continue
            par_env[env] = fam["versions"]
            for v in fam["versions"]:
                index_sha.setdefault(v["sha"], []).append((env, v))
        cles = sorted(
            {
                v["cle"]
                for vs in par_env.values()
                for v in vs
                if v["statut"] in ("active", "draft")
            }
        )
        lignes = []
        for cle in cles:
            ligne = {
                "famille": "arbre",
                "cle": cle,
                "libelle": "",
                "cellules": {},
                "diffs": {},
                "signaux": [],
            }
            for env in self.envs_releves:
                if env not in par_env:
                    ligne["cellules"][env] = None
                    continue
                actives = [
                    v
                    for v in par_env[env]
                    if v["cle"] == cle and v["statut"] == "active"
                ]
                brouillons = [
                    v
                    for v in par_env[env]
                    if v["cle"] == cle and v["statut"] == "draft"
                ]
                actives.sort(key=lambda v: v.get("active_le") or "", reverse=True)
                if len(actives) > 1:
                    ligne["signaux"].append(
                        {
                            "niveau": "rouge",
                            "code": "plusieurs_actifs",
                            "texte": f"{len(actives)} arbres actifs pour cette clé en {env}.",
                        }
                    )
                c = {"brouillons": [self._resume_brouillon(b) for b in brouillons]}
                if not actives:
                    c["absent"] = True
                else:
                    a = actives[0]
                    rev = a.get("derniere_revision") or {}
                    dates = [
                        x
                        for x in (a.get("active_le"), rev.get("date"), a.get("cree"))
                        if x
                    ]
                    c.update(
                        {
                            "sha": a["sha"],
                            "facettes": a["facettes"],
                            "date": max(dates) if dates else None,
                            "nom": a["nom"],
                            "pk": a["pk"],
                            "active_le": a.get("active_le"),
                            "cree": a.get("cree"),
                            "cree_par": a.get("cree_par"),
                            "noeuds": a.get("noeuds"),
                            "config": a.get("config"),
                            "revision": rev or None,
                            "journal_admin": a.get("journal_admin"),
                            "textes": {
                                "yaml": a.get("texte_yaml"),
                                "logique": a.get("texte_logique"),
                            },
                        }
                    )
                    if rev.get("date") and rev["date"] >= (a.get("active_le") or ""):
                        c["par"], c["detail"] = rev.get("par"), rev.get("detail")
                    else:
                        c["par"], c["detail"] = a.get("cree_par"), "activé"
                    ja = a.get("journal_admin") or {}
                    if ja.get("copie") and not (
                        rev.get("date") and rev["date"] > ja["date"]
                    ):
                        c["date"] = ja["copie"].get("date_origine")
                        c["copie"] = dict(ja["copie"], le=ja["date"], par=ja.get("par"))
                        c["date_source"] = "copie"
                        c["par"], c["detail"] = ja["copie"]["source"], ja.get("detail")
                    ligne["libelle"] = ligne["libelle"] or a["nom"]
                    # Filiation : cette version active existe-t-elle ailleurs
                    # comme archive ou brouillon ?
                    c["filiation"] = [
                        {
                            "env": e2,
                            "statut": v2["statut"],
                            "pk": v2["pk"],
                            "nom": v2["nom"],
                            "maj": v2.get("maj"),
                        }
                        for e2, v2 in index_sha.get(a["sha"], [])
                        if not (e2 == env and v2["pk"] == a["pk"])
                        and v2["statut"] != "active"
                    ]
                ligne["cellules"][env] = c
            if not ligne["libelle"]:
                for c in ligne["cellules"].values():
                    if c and c.get("brouillons"):
                        ligne["libelle"] = c["brouillons"][0]["nom"]
                        break
            versions = lettres(ligne["cellules"])
            ligne["versions"] = [
                {
                    k: v.get(k)
                    for k in ("lettre", "sha", "envs", "date", "retard_j", "origine")
                }
                for v in versions
            ]
            ligne["signaux"] += signaux_communs(
                ligne["cellules"], versions, self.envs_releves
            )
            ligne["signaux"] += self._signaux_arbre(ligne, versions)
            self.ajouter_diffs(ligne)
            ligne["facettes"] = facettes(ligne["cellules"])
            lignes.append(ligne)
        return lignes

    def _resume_brouillon(self, b):
        rev = b.get("derniere_revision") or {}
        return {
            "pk": b["pk"],
            "nom": b["nom"],
            "sha": b["sha"],
            "maj": rev.get("date") or b.get("maj"),
            "par": rev.get("par") or b.get("cree_par"),
            "verrou": b.get("verrou"),
        }

    def _signaux_arbre(self, ligne, versions):
        sig = []
        cel = ligne["cellules"]
        for env, c in cel.items():
            if not c or c.get("absent"):
                continue
            for f in c.get("filiation", []):
                if f["statut"] != "archive":
                    continue
                autre = cel.get(f["env"])
                if autre and not autre.get("absent") and autre["sha"] != c["sha"]:
                    sig.append(
                        {
                            "niveau": "orange",
                            "code": "retard",
                            "texte": f"{env} sert une version que {f['env']} a déjà remplacée "
                            f"(archive #{f['pk']} « {f['nom']} », archivée vers le {_court(f['maj'])}).",
                        }
                    )
            for b in c.get("brouillons", []):
                if b.get("verrou"):
                    sig.append(
                        {
                            "niveau": "info",
                            "code": "verrou",
                            "texte": f"Brouillon #{b['pk']} en cours d'édition en {env} "
                            f"(verrou {b['verrou']['par'] or '?'} depuis {_court(b['verrou']['le'])}).",
                        }
                    )
        vides = [
            e
            for e, c in cel.items()
            if c and not c.get("absent") and c["facettes"].get("yaml_brut") == SHA_VIDE
        ]
        if vides:
            sig.append(
                {
                    "niveau": "info",
                    "code": "yaml_vide",
                    "texte": f"YAML brut vide en {', '.join(vides)} : l'arbre a été chargé sans son YAML d'origine "
                    "(commentaires et ordre perdus, seule la logique JSON fait foi).",
                }
            )
        # Même logique, YAML brut différent : seulement de la mise en forme.
        par_sha = {}
        for env, c in cel.items():
            if c and not c.get("absent"):
                par_sha.setdefault(c["sha"], set()).add(c["facettes"]["yaml_brut"])
        for sha, yamls in par_sha.items():
            if len(yamls) > 1:
                sig.append(
                    {
                        "niveau": "info",
                        "code": "yaml_seul",
                        "texte": "Même logique, mais YAML brut différent (commentaires ou mise en forme).",
                    }
                )
        for env, c in cel.items():
            if c and c.get("absent") and c.get("brouillons"):
                sig.append(
                    {
                        "niveau": "info",
                        "code": "brouillon_seul",
                        "texte": f"{env} : pas d'arbre actif, {len(c['brouillons'])} brouillon(s) seulement.",
                    }
                )
        return sig

    # ─── référentiels ───────────────────────────────────────────────────
    def referentiel(self, famille):
        par_env = {}
        absente = []
        for env in self.envs_releves:
            fam = self.releves[env]["familles"].get(famille)
            if fam is None:
                continue
            if fam.get("absente"):
                absente.append(env)
            par_env[env] = fam["objets"]
        cles = sorted({k for objs in par_env.values() for k in objs})
        lignes = []
        for cle in cles:
            ligne = {
                "famille": famille,
                "cle": cle,
                "libelle": "",
                "cellules": {},
                "diffs": {},
                "signaux": [],
            }
            for env in self.envs_releves:
                if env not in par_env:
                    ligne["cellules"][env] = None
                    continue
                o = par_env[env].get(cle)
                if o is None:
                    ligne["cellules"][env] = {
                        "absent": True,
                        "table_absente": env in absente,
                    }
                    continue
                dates = sorted(
                    o.get("dates", []), key=lambda d: d.get("date") or "", reverse=True
                )
                date, trace, copie = date_auteur(dates)
                ligne["cellules"][env] = {
                    "sha": o["sha"],
                    "pk": o.get("pk"),
                    "facettes": o["facettes"],
                    "date": date,
                    "date_source": "copie" if copie else trace.get("source"),
                    "par": (copie["copie"]["source"] if copie else trace.get("par")),
                    "detail": trace.get("detail"),
                    "copie": copie
                    and dict(copie["copie"], le=copie["date"], par=copie.get("par")),
                    "connu_depuis": o.get("connu_depuis"),
                    "dates": dates,
                    "textes": {"contenu": o["texte"]},
                }
                ligne["libelle"] = ligne["libelle"] or o.get("libelle", "")
            versions = lettres(ligne["cellules"])
            ligne["versions"] = [
                {
                    k: v.get(k)
                    for k in ("lettre", "sha", "envs", "date", "retard_j", "origine")
                }
                for v in versions
            ]
            ligne["signaux"] += signaux_communs(
                ligne["cellules"], versions, self.envs_releves
            )
            if absente:
                ligne["signaux"].append(
                    {
                        "niveau": "info",
                        "code": "table_absente",
                        "texte": f"Table absente en {', '.join(absente)}.",
                    }
                )
            self.ajouter_diffs(ligne)
            ligne["facettes"] = facettes(ligne["cellules"])
            lignes.append(ligne)
        return lignes


def facettes(cellules):
    """Par champ : lettre de valeur par env (même lettre = même valeur)."""
    noms = sorted(
        {
            f
            for c in cellules.values()
            if c and not c.get("absent")
            for f in c.get("facettes", {})
        }
    )
    out = []
    for nom in noms:
        vus = {}
        par_env = {}
        for env, c in cellules.items():
            if not c or c.get("absent"):
                continue
            h = c.get("facettes", {}).get(nom)
            if h is None:
                par_env[env] = None
                continue
            if h not in vus:
                vus[h] = chr(ord("a") + len(vus))
            par_env[env] = vus[h]
        out.append({"champ": nom, "envs": par_env, "distincts": len(vus)})
    return out


def score(ligne):
    return sum(POIDS[s["niveau"]] for s in ligne["signaux"])


def construire(releves, echecs, ordre):
    b = Constructeur(releves, ordre)
    familles = []
    for fid, titre, groupe in FAMILLES:
        lignes = b.arbres() if fid == "arbre" else b.referentiel(fid)
        for lg in lignes:
            lg["score"] = score(lg)
            lg["resumes"] = demandes_resumes(lg, lg["versions"])
        lignes.sort(key=lambda lg: (-lg["score"], lg["cle"]))
        familles.append({"id": fid, "titre": titre, "groupe": groupe, "lignes": lignes})
    envs = []
    for env in ordre:
        r = releves.get(env)
        envs.append(
            {
                "id": env,
                "releve": r is not None,
                "releve_le": r and r.get("releve_le"),
                "duree_s": r and r.get("duree_s"),
                "code": r and r.get("code"),
                "meta": r and r.get("meta"),
                "erreurs": (r and r.get("erreurs")) or [],
                "liens": r and r.get("liens"),
                "echec": echecs.get(env),
            }
        )
    textes = {h: b.textes[h] for h in b.textes_utiles if h in b.textes}
    return {
        "genere_le": datetime.datetime.now(datetime.timezone.utc).isoformat(
            timespec="seconds"
        ),
        "envs": envs,
        "familles": familles,
        "diffs": b.diffs,
        "textes": textes,
    }


def page(releves, echecs, ordre):
    data = construire(releves, echecs, ordre)
    gabarit = (ICI / "template.html").read_text()
    js = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return gabarit.replace("/*__DONNEES__*/null", js)
