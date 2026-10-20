"""Relevé en lecture seule des objets éditables d'une base nitrates.

Exécuté DANS le conteneur Django local (qui a psycopg), quelle que soit la
base visée : base locale, ou base Scalingo joignable par un tunnel. On ne
passe volontairement pas par l'ORM : le code local peut être plus récent que
le schéma d'une base distante (prod en retard d'une release), et une requête
ORM sur une colonne absente casse tout le relevé. Le SQL brut + l'introspection
du schéma tolèrent ces écarts.

Sortie : un document JSON sur stdout. Rien n'est écrit en base : la session
est ouverte en lecture seule (default_transaction_read_only + read_only).

Empreintes : SHA-256 sur une sérialisation JSON canonique (clés triées,
séparateurs fixes) des champs stockés. Aucune normalisation sémantique : deux
contenus qui diffèrent d'un octet ont deux empreintes différentes. Les
champs techniques non portables (id, horodatages, auteur, verrou) sont exclus
et les clés étrangères sont remplacées par la clé naturelle de l'objet visé.

DSN : lu dans la variable globale OPS_DSN (injectée par l'orchestrateur, qui
la transmet par stdin pour qu'elle n'apparaisse dans aucune ligne de
commande), sinon reconstruit depuis POSTGRES_* (base locale du conteneur).
"""

import datetime
import decimal
import hashlib
import json
import os
import re
import sys

# Version du format du relevé : à incrémenter dès que le calcul des empreintes
# change (sinon le journal verrait tous les objets « modifiés »).
SCHEMA = 2

# Champs exclus des empreintes : techniques, propres à chaque base.
VOLATILS = {
    "id",
    "created_at",
    "updated_at",
    "modifie_le",
    "date_modification",
    "activated_at",
    "locked_at",
    "locked_by_id",
    "created_by_id",
    "parent_id",
}

# Référentiels comparés par clé naturelle. `ct` = (app_label, model) pour
# retrouver les éditions dans le journal de l'admin ; `rev` = type_objet dans
# RevisionContenu quand la table existe (branche historique-pc).
REFERENTIELS = [
    {
        "famille": "pc",
        "table": "nitrates_codeprescription",
        "cle": ["identifiant"],
        "libelle": ["@titre_blocs", "texte_court", "mots_cles"],
        # Champs décommissionnés (migration 0042, 0.6.4) : encore présents en
        # local et en prod tant qu'ils n'ont pas la 0.6.4, jamais comparés.
        "ignorer": ["texte_court", "texte_redaction_initiale"],
        "ct": ("nitrates", "codeprescription"),
        "rev": "pc",
        "m2m": [
            {
                "champ": "composants_fusion",
                "table": "nitrates_codeprescription_composants_fusion",
                "de": "from_codeprescription_id",
                "vers": "to_codeprescription_id",
                "cible": "nitrates_codeprescription",
            }
        ],
    },
    {
        "famille": "contenu",
        "table": "nitrates_contenurichdsfr",
        "cle": ["cle"],
        "libelle": "libelle_admin",
        "ct": ("nitrates", "contenurichdsfr"),
        "rev": "contenu_rich",
        "date_col": "updated_at",
    },
    {
        "famille": "culture",
        "table": "nitrates_culture",
        "cle": ["identifiant"],
        "libelle": "libelle_public",
        "ct": ("nitrates", "culture"),
    },
    {
        "famille": "brancheculturale",
        "table": "nitrates_brancheculturale",
        "cle": ["identifiant"],
        "libelle": "libelle_court",
        "ct": ("nitrates", "brancheculturale"),
    },
    {
        "famille": "groupecultureui",
        "table": "nitrates_groupecultureui",
        "cle": ["identifiant"],
        "libelle": "libelle_public",
        "ct": ("nitrates", "groupecultureui"),
    },
    {
        "famille": "fertilisant",
        "table": "nitrates_fertilisant",
        "cle": ["identifiant"],
        "libelle": "libelle_public",
        "ct": ("nitrates", "fertilisant"),
    },
    {
        "famille": "notereglementaire",
        "table": "nitrates_notereglementaire",
        "cle": ["identifiant"],
        "libelle": "libelle_court",
        "ct": ("nitrates", "notereglementaire"),
    },
    {
        "famille": "evenementphenologique",
        "table": "nitrates_evenementphenologique",
        "cle": ["identifiant"],
        "libelle": "libelle_public",
        "ct": ("nitrates", "evenementphenologique"),
    },
    {
        "famille": "lienreference",
        "table": "nitrates_lienreference",
        "cle": ["identifiant"],
        "libelle": "libelle",
        "ct": ("nitrates", "lienreference"),
    },
    {
        "famille": "ouverture",
        "table": "nitrates_departementouverture",
        "cle": ["code"],
        "libelle": "nom",
        "ct": ("nitrates", "departementouverture"),
    },
    {
        "famille": "couleurzone",
        "table": "nitrates_couleurzone",
        "cle": ["map_type", "cle"],
        "libelle": "libelle",
        "ct": ("nitrates", "couleurzone"),
    },
]

OID_JSON = {114, 3802}  # json, jsonb

# Colonnes « modifié le » reconnues, dans l'ordre de préférence.
COLONNES_DATE = ("updated_at", "modifie_le", "date_modification")

# Colonne servant de clé naturelle quand une FK pointe vers une table.
CLES_NATURELLES = ("identifiant", "cle", "code")


def _defaut(v):
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return str(v)
    if isinstance(v, (bytes, memoryview)):
        return bytes(v).hex()
    return str(v)


def canon(obj):
    return json.dumps(
        obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=_defaut
    )


def sha_obj(obj):
    return hashlib.sha256(canon(obj).encode("utf-8")).hexdigest()


def sha_txt(txt):
    return hashlib.sha256((txt or "").encode("utf-8")).hexdigest()


def joli(obj):
    """Rendu lisible pour les diffs (stable, clés triées)."""
    return json.dumps(
        obj, sort_keys=True, ensure_ascii=False, indent=2, default=_defaut
    )


def iso(dt):
    return dt.isoformat(timespec="seconds") if dt else None


class Releve:
    def __init__(self, conn):
        self.conn = conn
        self.contenus = {}  # sha du texte affichable -> texte (pour les diffs)
        self.erreurs = []
        self._cols = {}

    # ─── utilitaires SQL ────────────────────────────────────────────────
    def q(self, sql, params=None):
        with self.conn.cursor() as cur:
            cur.execute(sql, params or ())
            cols = [d.name for d in cur.description]
            # Sous Django, le JSON arrive en texte (Django le décode lui-même
            # dans JSONField) ; avec psycopg nu, il arrive déjà décodé. On
            # aligne les deux, sinon les empreintes divergent selon le chemin.
            json_cols = {
                i for i, d in enumerate(cur.description) if d.type_code in OID_JSON
            }
            lignes = []
            for r in cur.fetchall():
                if json_cols:
                    r = [
                        json.loads(v) if i in json_cols and isinstance(v, str) else v
                        for i, v in enumerate(r)
                    ]
                lignes.append(dict(zip(cols, r)))
            return lignes

    def table_existe(self, table):
        return (
            self.q("SELECT to_regclass(%s) AS t", ("public." + table,))[0]["t"]
            is not None
        )

    def colonnes(self, table):
        if table not in self._cols:
            self._cols[table] = [
                (r["column_name"], r["data_type"])
                for r in self.q(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
                    (table,),
                )
            ]
        return self._cols[table]

    def fks(self, table):
        return {
            r["col"]: r["ref"]
            for r in self.q(
                """
                SELECT a.attname AS col, cl2.relname AS ref
                FROM pg_constraint c
                JOIN pg_class cl ON cl.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = cl.relnamespace AND n.nspname = 'public'
                JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
                JOIN pg_class cl2 ON cl2.oid = c.confrelid
                WHERE c.contype = 'f' AND cl.relname = %s
                """,
                (table,),
            )
        }

    def index_cles_naturelles(self, table):
        """id -> clé naturelle lisible de la table visée par une FK."""
        noms = [c for c, _ in self.colonnes(table)]
        if table == "geodata_map":
            rows = self.q("SELECT id, name, version FROM geodata_map")
            return {r["id"]: f"{r['name']}@{r['version'] or '-'}" for r in rows}
        for c in CLES_NATURELLES:
            if c in noms:
                return {
                    r["id"]: r["k"]
                    for r in self.q(f'SELECT id, "{c}" AS k FROM "{table}"')
                }
        return {
            r["id"]: f"#{r['id']} (non portable)"
            for r in self.q(f'SELECT id FROM "{table}"')
        }

    def nom_user(self, nom, email):
        if nom:
            return nom
        if email:
            return email.split("@")[0]
        return None

    def journal_admin(self, app_label, model):
        """Dernière entrée du journal admin par object_id (pk en texte)."""
        if not self.table_existe("django_admin_log"):
            return {}
        rows = self.q(
            """
            SELECT DISTINCT ON (l.object_id) l.object_id, l.action_time, l.action_flag,
                   l.change_message, u.name, u.email,
                   count(*) OVER (PARTITION BY l.object_id) AS n
            FROM django_admin_log l
            JOIN django_content_type ct ON ct.id = l.content_type_id
            LEFT JOIN users_user u ON u.id = l.user_id
            WHERE ct.app_label = %s AND ct.model = %s
            ORDER BY l.object_id, l.action_time DESC
            """,
            (app_label, model),
        )
        out = {}
        for r in rows:
            out[r["object_id"]] = {
                "date": iso(r["action_time"]),
                "par": self.nom_user(r["name"], r["email"]),
                "detail": resume_change_message(r["change_message"], r["action_flag"]),
                "n": r["n"],
            }
            copie = lire_copie(r["change_message"])
            if copie:
                out[r["object_id"]]["copie"] = copie
        return out

    def revisions_contenu(self, type_objet):
        """Dernière RevisionContenu par identifiant (si la table existe)."""
        if not self.table_existe("nitrates_revisioncontenu"):
            return None
        rows = self.q(
            """
            SELECT DISTINCT ON (r.identifiant) r.identifiant, r.created_at, r.action,
                   r.origine, r.motif, r.source, u.name, u.email,
                   count(*) OVER (PARTITION BY r.identifiant) AS n
            FROM nitrates_revisioncontenu r
            LEFT JOIN users_user u ON u.id = r.auteur_id
            WHERE r.type_objet = %s
              -- « État initial » = instantané pris à l'ouverture de l'historique
              -- (déploiement de la 0.6.4) : ce n'est pas une écriture du contenu.
              AND coalesce(r.motif, '') NOT LIKE 'État initial%%'
            ORDER BY r.identifiant, r.created_at DESC
            """,
            (type_objet,),
        )
        out = {}
        for r in rows:
            out[r["identifiant"]] = {
                "date": iso(r["created_at"]),
                "par": self.nom_user(r["name"], r["email"]),
                "detail": " · ".join(
                    x
                    for x in (r["action"], r["origine"], (r["motif"] or "")[:160])
                    if x
                ),
                "n": r["n"],
            }
            copie = lire_copie(r["motif"])
            if copie:
                out[r["identifiant"]]["copie"] = copie
        return out

    def ouvertures_historique(self, type_objet):
        """Date de l'instantané « État initial » par identifiant (si l'historique existe)."""
        if not self.table_existe("nitrates_revisioncontenu"):
            return {}
        rows = self.q(
            """
            SELECT identifiant, min(created_at) AS le
            FROM nitrates_revisioncontenu
            WHERE type_objet = %s AND coalesce(motif, '') LIKE 'État initial%%'
            GROUP BY identifiant
            """,
            (type_objet,),
        )
        return {r["identifiant"]: iso(r["le"]) for r in rows}

    def garder(self, texte):
        h = sha_txt(texte)
        self.contenus[h] = texte
        return h

    # ─── référentiels génériques ───────────────────────────────────────
    def referentiel(self, spec):
        table = spec["table"]
        if not self.table_existe(table):
            return {"absente": True, "objets": {}}
        cols = [(c, t) for c, t in self.colonnes(table) if t != "USER-DEFINED"]
        fks = self.fks(table)
        resolveurs = {
            c: self.index_cles_naturelles(ref)
            for c, ref in fks.items()
            if c not in VOLATILS
        }
        rows = self.q(
            f'SELECT {", ".join(chr(34) + c + chr(34) for c, _ in cols)} FROM "{table}"'
        )
        m2m = {}
        for m in spec.get("m2m", []):
            if not self.table_existe(m["table"]):
                continue
            idx = self.index_cles_naturelles(m["cible"])
            for r in self.q(
                f'SELECT "{m["de"]}" AS de, "{m["vers"]}" AS vers FROM "{m["table"]}"'
            ):
                m2m.setdefault((m["champ"], r["de"]), []).append(
                    idx.get(r["vers"], r["vers"])
                )
        journal = self.journal_admin(*spec["ct"])
        revs = self.revisions_contenu(spec["rev"]) if spec.get("rev") else None
        ouvertures = self.ouvertures_historique(spec["rev"]) if spec.get("rev") else {}
        # Date de modification portée par la table elle-même, si elle existe
        # (ajout de updated_at sur les PC en cours, octobre 2026).
        noms_cols = {c for c, _ in cols}
        date_col = spec.get("date_col") or next(
            (c for c in COLONNES_DATE if c in noms_cols), None
        )
        objets = {}
        for r in rows:
            champs = {}
            for c, _ in cols:
                if c in VOLATILS or c in spec.get("ignorer", ()):
                    continue
                v = r[c]
                if c in resolveurs:
                    if v is not None:
                        v = resolveurs[c].get(v, f"#{v} (introuvable)")
                    c = c[:-3] if c.endswith("_id") else c
                champs[c] = v
            for m in spec.get("m2m", []):
                champs[m["champ"]] = sorted(m2m.get((m["champ"], r["id"]), []))
            cle = "/".join(str(r[c]) for c in spec["cle"])
            dates = []
            if date_col and r.get(date_col):
                dates.append({"date": iso(r[date_col]), "source": date_col})
            j = journal.get(str(r["id"]))
            if j:
                dates.append(dict(j, source="journal admin"))
            if revs is not None and revs.get(cle):
                dates.append(dict(revs[cle], source="historique contenus"))
            libelles = (
                spec["libelle"]
                if isinstance(spec["libelle"], list)
                else [spec["libelle"]]
            )
            objets[cle] = {
                "libelle": next(
                    (v for v in (libelle_colonne(r, x) for x in libelles) if v), ""
                )[:140],
                # Date de l'instantané « État initial » : le contenu existait
                # déjà à cette date. Affichée, jamais utilisée pour l'ordre.
                "connu_depuis": ouvertures.get(cle),
                "sha": sha_obj(champs),
                "facettes": {k: sha_obj(v) for k, v in champs.items()},
                "texte": self.garder(joli(champs)),
                "dates": dates,
                "pk": r["id"],
            }
        return {
            "absente": False,
            "objets": objets,
            "historique_contenus": revs is not None,
        }

    # ─── arbres de décision ────────────────────────────────────────────
    def arbres(self):
        noms = {c for c, _ in self.colonnes("nitrates_decisiontree")}
        a_map = "activation_map_id" in noms
        if a_map:
            colonnes_map = "m.name AS map_name, m.version AS map_version,"
        else:
            colonnes_map = "NULL AS map_name, NULL AS map_version,"
        rows = self.q(
            f"""
            SELECT t.id, t.name, t.status, t.scope, t.region_code, t.weight,
                   t.contenu, t.contenu_yaml_brut, t.created_at, t.updated_at,
                   t.activated_at, t.locked_at, t.parent_id,
                   {colonnes_map}
                   cu.name AS cree_par_nom, cu.email AS cree_par_email,
                   lu.name AS verrou_nom, lu.email AS verrou_email
            FROM nitrates_decisiontree t
            {"LEFT JOIN geodata_map m ON m.id = t.activation_map_id" if a_map else ""}
            LEFT JOIN users_user cu ON cu.id = t.created_by_id
            LEFT JOIN users_user lu ON lu.id = t.locked_by_id
            ORDER BY t.id
            """
        )
        revs = {
            r["tree_id"]: r
            for r in self.q(
                """
                SELECT DISTINCT ON (r.tree_id) r.tree_id, r.created_at, r.action,
                       r.description, r.target_path, u.name, u.email,
                       count(*) OVER (PARTITION BY r.tree_id) AS n
                FROM nitrates_decisiontreerevision r
                LEFT JOIN users_user u ON u.id = r.created_by_id
                ORDER BY r.tree_id, r.created_at DESC
                """
            )
        }
        journal = self.journal_admin("nitrates", "decisiontree")
        versions = []
        for r in rows:
            config = {
                "scope": r["scope"],
                "region_code": r["region_code"] or "",
                "weight": r["weight"],
                "activation_map": (
                    f"{r['map_name']}@{r['map_version'] or '-'}"
                    if r["map_name"]
                    else None
                ),
            }
            sha_logique = sha_obj(r["contenu"])
            sha_config = sha_obj(config)
            sha_yaml = sha_txt(r["contenu_yaml_brut"])
            v = {
                "pk": r["id"],
                "nom": r["name"],
                "statut": r["status"],
                "cle": cle_arbre(r["scope"], r["region_code"], r["map_name"]),
                "config": config,
                # Empreinte principale = ce qui s'exécute : logique + activation.
                "sha": sha_obj({"contenu": r["contenu"], "config": config}),
                "facettes": {
                    "logique": sha_logique,
                    "activation": sha_config,
                    "yaml_brut": sha_yaml,
                },
                "cree": iso(r["created_at"]),
                "maj": iso(r["updated_at"]),
                "active_le": iso(r["activated_at"]),
                "cree_par": self.nom_user(r["cree_par_nom"], r["cree_par_email"]),
                "verrou": (
                    {
                        "par": self.nom_user(r["verrou_nom"], r["verrou_email"]),
                        "le": iso(r["locked_at"]),
                    }
                    if r["locked_at"]
                    else None
                ),
                "parent_pk": r["parent_id"],
                "noeuds": compter_noeuds(r["contenu"]),
            }
            rv = revs.get(r["id"])
            if rv:
                v["derniere_revision"] = {
                    "date": iso(rv["created_at"]),
                    "par": self.nom_user(rv["name"], rv["email"]),
                    "detail": " · ".join(
                        x
                        for x in (
                            rv["action"],
                            rv["target_path"],
                            (rv["description"] or "")[:160],
                        )
                        if x
                    ),
                    "n": rv["n"],
                }
            j = journal.get(str(r["id"]))
            if j:
                v["journal_admin"] = j
            # Les textes (pour les diffs) ne descendent que pour les versions
            # vivantes ; les archives ne servent qu'à la filiation par empreinte.
            if r["status"] in ("active", "draft"):
                v["texte_yaml"] = self.garder(r["contenu_yaml_brut"] or "")
                v["texte_logique"] = self.garder(
                    joli({"config": config, "contenu": r["contenu"]})
                )
            versions.append(v)
        return {"versions": versions}

    def meta(self):
        r = self.q(
            "SELECT current_database() AS db, now() AS maintenant, "
            "current_setting('server_version') AS pg, "
            "current_setting('transaction_read_only') AS ro"
        )[0]
        migr = None
        if self.table_existe("django_migrations"):
            m = self.q(
                "SELECT name, applied FROM django_migrations WHERE app='nitrates' "
                "ORDER BY applied DESC, id DESC LIMIT 1"
            )
            if m:
                migr = {"nom": m[0]["name"], "le": iso(m[0]["applied"])}
        return {
            "base": r["db"],
            "horloge_base": iso(r["maintenant"]),
            "postgres": r["pg"],
            "lecture_seule": r["ro"],
            "derniere_migration_nitrates": migr,
        }


def libelle_colonne(r, nom):
    """Valeur d'une colonne pour le libellé ; `@titre_blocs` = premier titre des blocs riches."""
    if nom != "@titre_blocs":
        return str(r[nom]) if r.get(nom) else ""
    blocs = r.get("blocs") or []
    if isinstance(blocs, dict):
        blocs = blocs.get("blocs", [])
    blocs = [b for b in blocs if isinstance(b, dict)]
    # Le titre principal d'abord, sinon le premier texte venu.
    for bloc in sorted(blocs, key=lambda b: b.get("type") != "titre_principal"):
        texte = _texte_de(bloc.get("data"))
        if texte:
            return texte
    return ""


def _texte_de(data):
    if not isinstance(data, dict):
        return ""
    t = data.get("texte")
    if isinstance(t, str):
        return t.strip()
    if isinstance(t, list):
        return "".join(
            x.get("texte", "") if isinstance(x, dict) else str(x) for x in t
        ).strip()
    return ""


def cle_arbre(scope, region_code, map_name):
    cle = scope or "?"
    if region_code:
        cle += "/" + region_code
    if map_name:
        cle += " · " + map_name
    return cle


def compter_noeuds(obj):
    n = 0
    pile = [obj]
    while pile:
        x = pile.pop()
        if isinstance(x, dict):
            n += 1
            pile.extend(x.values())
        elif isinstance(x, list):
            pile.extend(x)
    return n


# Message écrit au journal admin par une copie nitrates-ops (apply_lot.py).
# Une copie n'écrit pas de contenu neuf : sa date ne doit pas rajeunir la
# version. On garde la date d'écriture d'origine quand elle est connue.
COPIE_RE = re.compile(
    r"Transfert nitrates-ops (T-\d+) depuis (\w+) \(version ([0-9a-f]+)(?:, écrite le ([^)]+))?\)"
)


def lire_copie(msg):
    m = COPIE_RE.search(msg or "")
    if not m:
        return None
    origine = m.group(4)
    return {
        "tache": m.group(1),
        "source": m.group(2),
        "version": m.group(3),
        "date_origine": None if not origine or origine == "date inconnue" else origine,
    }


def resume_change_message(msg, flag):
    action = {1: "ajout", 2: "modification", 3: "suppression"}.get(flag, "")
    try:
        data = json.loads(msg) if msg else []
    except ValueError:
        return f"{action} {msg[:120]}".strip()
    champs = []
    for d in data if isinstance(data, list) else []:
        for k in ("changed", "added", "deleted"):
            if k in d:
                champs += d[k].get("fields", []) if isinstance(d[k], dict) else []
    return f"{action} {', '.join(champs)}".strip() if champs else action


def dsn():
    d = globals().get("OPS_DSN") or os.environ.get("OPS_DSN")
    if d:
        return d
    e = os.environ
    return (
        f"host={e['POSTGRES_HOST']} port={e.get('POSTGRES_PORT', '5432')} "
        f"dbname={e['POSTGRES_DB']} user={e['POSTGRES_USER']} password={e['POSTGRES_PASSWORD']}"
    )


def main():
    import psycopg  # seulement pour le relevé direct ; apply_lot passe par Django

    conn = psycopg.connect(
        dsn(),
        options="-c default_transaction_read_only=on -c statement_timeout=120000",
        connect_timeout=20,
    )
    conn.read_only = True
    rel = Releve(conn)
    out = {"schema": SCHEMA, "meta": rel.meta(), "familles": {}, "erreurs": []}
    if out["meta"]["lecture_seule"] != "on":
        raise SystemExit("Session non lecture seule, abandon.")
    try:
        out["familles"]["arbre"] = rel.arbres()
    except Exception as e:  # noqa: BLE001 - un relevé partiel vaut mieux que rien
        conn.rollback()
        out["erreurs"].append({"famille": "arbre", "erreur": repr(e)[:400]})
    for spec in REFERENTIELS:
        try:
            out["familles"][spec["famille"]] = rel.referentiel(spec)
        except Exception as e:  # noqa: BLE001
            conn.rollback()
            out["erreurs"].append({"famille": spec["famille"], "erreur": repr(e)[:400]})
    out["contenus"] = rel.contenus
    conn.close()
    sys.stdout.write(json.dumps(out, ensure_ascii=False, default=_defaut))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
