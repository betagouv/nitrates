"""Tests de la comparaison entre environnements (sans base ni réseau).

python3 -m unittest discover -s tools/ops-dashboard
"""

import json
import unittest
from pathlib import Path

import render

ORDRE = ["local", "dev", "staging", "prod"]


def cel(sha, date=None):
    return {"sha": sha, "date": date, "facettes": {"x": sha}}


def codes(sig):
    return [s["code"] for s in sig]


class LettresTest(unittest.TestCase):
    def test_a_est_la_version_la_plus_recente(self):
        cellules = {
            "dev": cel("v1", "2026-10-01T10:00:00+00:00"),
            "staging": cel("v2", "2026-10-05T10:00:00+00:00"),
            "prod": cel("v1", "2026-09-01T10:00:00+00:00"),
        }
        versions = render.lettres(cellules)
        self.assertEqual([v["sha"] for v in versions], ["v2", "v1"])
        self.assertEqual(cellules["staging"]["version"], "A")
        self.assertEqual(cellules["dev"]["version"], "B")
        self.assertEqual(cellules["prod"]["version"], "B")

    def test_version_datee_avant_version_sans_date(self):
        cellules = {"dev": cel("v1"), "staging": cel("v2", "2020-01-01T00:00:00+00:00")}
        render.lettres(cellules)
        self.assertEqual(cellules["staging"]["version"], "A")

    def test_absent_ignore(self):
        cellules = {"dev": cel("v1"), "staging": {"absent": True}}
        self.assertEqual(len(render.lettres(cellules)), 1)
        self.assertNotIn("version", cellules["staging"])


class SignauxTest(unittest.TestCase):
    def signaux(self, cellules):
        versions = render.lettres(cellules)
        return render.signaux_communs(cellules, versions, ORDRE)

    def test_identique_partout_aucun_signal(self):
        self.assertEqual(self.signaux({e: cel("v") for e in ORDRE}), [])

    def test_prod_differente_de_staging(self):
        c = {e: cel("v") for e in ORDRE}
        c["prod"] = cel("w")
        self.assertIn("prod_staging", codes(self.signaux(c)))

    def test_aval_plus_recent(self):
        c = {
            "local": cel("v"),
            "dev": cel("v", "2026-10-01T00:00:00+00:00"),
            "staging": cel("w", "2026-10-03T00:00:00+00:00"),
            "prod": cel("w"),
        }
        sig = self.signaux(c)
        self.assertIn("aval_plus_recent", codes(sig))
        self.assertIn("dev → staging", " ".join(s["texte"] for s in sig))

    def test_aval_date_amont_sans_trace(self):
        # Cas pc8 : édition juriste en staging, dev sans aucune trace.
        c = {
            "dev": cel("v"),
            "staging": cel("w", "2026-09-10T00:00:00+00:00"),
            "prod": cel("w"),
        }
        self.assertIn("aval_plus_recent", codes(self.signaux(c)))

    def test_amont_plus_recent_pas_de_signal_aval(self):
        c = {
            "dev": cel("v", "2026-10-14T00:00:00+00:00"),
            "staging": cel("w", "2026-10-01T00:00:00+00:00"),
            "prod": cel("w"),
        }
        self.assertNotIn("aval_plus_recent", codes(self.signaux(c)))

    def test_cree_en_aval(self):
        c = {
            "local": cel("v"),
            "dev": cel("v"),
            "staging": {"absent": True},
            "prod": cel("v"),
        }
        sig = self.signaux(c)
        self.assertIn("cree_en_aval", codes(sig))
        self.assertEqual(
            [s for s in sig if s["code"] == "cree_en_aval"][0]["niveau"], "rouge"
        )

    def test_en_attente(self):
        c = {
            "local": cel("v"),
            "dev": cel("v"),
            "staging": {"absent": True},
            "prod": {"absent": True},
        }
        sig = self.signaux(c)
        self.assertEqual(codes(sig), ["en_attente"])

    def test_env_non_releve(self):
        c = {"local": None, "dev": cel("v"), "staging": cel("v"), "prod": cel("v")}
        self.assertEqual(self.signaux(c), [])


def version_arbre(pk, sha, statut, cle="region/44", **kw):
    v = {
        "pk": pk,
        "nom": f"arbre {pk}",
        "statut": statut,
        "cle": cle,
        "sha": sha,
        "config": {"weight": 10},
        "facettes": {
            "logique": sha,
            "activation": "a",
            "yaml_brut": kw.pop("yaml", "y"),
        },
        "cree": "2026-10-01T00:00:00+00:00",
        "maj": "2026-10-01T00:00:00+00:00",
        "active_le": kw.pop("active_le", None),
        "texte_yaml": "ty" + sha,
        "texte_logique": "tl" + sha,
        "noeuds": 3,
    }
    v.update(kw)
    return v


def releve(versions, contenus=None):
    fam = {"versions": versions}
    return {
        "familles": {"arbre": fam},
        "contenus": contenus or {},
        "meta": {},
        "erreurs": [],
    }


class ArbresTest(unittest.TestCase):
    def test_retard_detecte_par_filiation(self):
        textes = {"tyA": "a: 1", "tlA": "{}", "tyB": "a: 2", "tlB": "{ }"}
        releves = {
            "dev": releve(
                [
                    version_arbre(1, "A", "archive"),
                    version_arbre(
                        2, "B", "active", active_le="2026-10-10T00:00:00+00:00"
                    ),
                ],
                textes,
            ),
            "staging": releve(
                [
                    version_arbre(
                        7, "A", "active", active_le="2026-10-02T00:00:00+00:00"
                    )
                ],
                textes,
            ),
        }
        data = render.construire(releves, {}, ORDRE)
        ligne = data["familles"][0]["lignes"][0]
        self.assertEqual(ligne["cellules"]["dev"]["version"], "A")
        self.assertEqual(ligne["cellules"]["staging"]["version"], "B")
        self.assertIn("retard", codes(ligne["signaux"]))
        self.assertIsNone(ligne["cellules"].get("local"))  # env sans relevé
        # Un diff par nature de texte, entre dev et staging.
        self.assertEqual(set(ligne["diffs"]), {"yaml", "logique"})

    def test_yaml_vide_et_yaml_seul(self):
        releves = {
            "dev": releve([version_arbre(1, "A", "active", yaml=render.SHA_VIDE)]),
            "staging": releve([version_arbre(2, "A", "active", yaml="autre")]),
        }
        ligne = render.construire(releves, {}, ORDRE)["familles"][0]["lignes"][0]
        self.assertEqual(len(ligne["versions"]), 1)
        self.assertIn("yaml_vide", codes(ligne["signaux"]))
        self.assertIn("yaml_seul", codes(ligne["signaux"]))

    def test_brouillon_seul(self):
        releves = {"dev": releve([version_arbre(3, "C", "draft", cle="region/53")])}
        ligne = render.construire(releves, {}, ORDRE)["familles"][0]["lignes"][0]
        self.assertTrue(ligne["cellules"]["dev"]["absent"])
        self.assertIn("brouillon_seul", codes(ligne["signaux"]))


class FacettesTest(unittest.TestCase):
    def test_lettres_par_champ(self):
        cellules = {
            "dev": {"sha": "1", "facettes": {"blocs": "x", "texte": "t"}},
            "staging": {"sha": "2", "facettes": {"blocs": "y", "texte": "t"}},
            "prod": {"absent": True},
        }
        f = {x["champ"]: x for x in render.facettes(cellules)}
        self.assertEqual(f["blocs"]["distincts"], 2)
        self.assertEqual(f["texte"]["distincts"], 1)
        self.assertNotIn("prod", f["blocs"]["envs"])


if __name__ == "__main__":
    unittest.main()


class RetardEtResumesTest(unittest.TestCase):
    def test_retard_en_jours_sur_la_plus_recente(self):
        cellules = {
            "dev": cel("v1", "2026-10-11T00:00:00+00:00"),
            "staging": cel("v2", "2026-10-01T00:00:00+00:00"),
            "prod": cel("v3"),
        }
        render.lettres(cellules)
        self.assertEqual(cellules["dev"]["retard_j"], 0)
        self.assertEqual(cellules["staging"]["retard_j"], 10)
        self.assertIsNone(cellules["prod"]["retard_j"])

    def test_resume_oriente_ancienne_vers_recente(self):
        releves = {
            "dev": releve(
                [version_arbre(1, "A", "active", active_le="2026-10-10T00:00:00+00:00")]
            ),
            "staging": releve(
                [version_arbre(2, "B", "active", active_le="2026-10-01T00:00:00+00:00")]
            ),
        }
        ligne = render.construire(releves, {}, ORDRE)["familles"][0]["lignes"][0]
        (r,) = ligne["resumes"]
        self.assertEqual((r["de"], r["vers"], r["nature"]), ("B", "A", "logique"))
        self.assertEqual(r["cle"], render.cle_resume("logique", "tlB", "tlA"))


class TransfertsTest(unittest.TestCase):
    def setUp(self):
        import executeur
        import serveur

        self.executeur, self.serveur = executeur, serveur
        textes = {
            "tA": json.dumps({"identifiant": "pc8", "texte_court": "x"}),
            "tB": "{}",
        }
        objets = {
            "pc8": {
                "sha": "A",
                "facettes": {"texte_court": "f"},
                "texte": "tA",
                "dates": [],
                "libelle": "",
            }
        }
        self.releves = {
            "staging": {"familles": {"pc": {"objets": objets}}, "contenus": textes},
            "dev": {
                "familles": {
                    "pc": {"objets": {"pc8": dict(objets["pc8"], sha="B", texte="tB")}}
                },
                "contenus": textes,
            },
        }

    def etat(self):
        class Faux:
            pass

        e = Faux()
        e.verrou = __import__("threading").RLock()
        e.envs = {"local": {}, "dev": {}, "staging": {}, "prod": {}}
        e.politique = {"local": "reel", "dev": "reel", "staging": "simulation"}
        e.releves = self.releves
        e.creees = []
        e.nouvelle_tache = lambda *a, **k: e.creees.append(k) or {
            "id": f"T-{len(e.creees):04d}"
        }
        return e

    def test_refus_vers_prod_et_objet_absent(self):
        e = self.etat()
        with self.assertRaisesRegex(ValueError, "prod désactivée"):
            self.serveur.creer_transferts(
                e,
                [{"famille": "pc", "cle": "pc8", "source": "staging", "cible": "prod"}],
            )
        with self.assertRaisesRegex(ValueError, "absent"):
            self.serveur.creer_transferts(
                e,
                [{"famille": "pc", "cle": "pc9", "source": "staging", "cible": "dev"}],
            )

    def test_une_tache_par_couple_avec_mode_de_la_cible(self):
        e = self.etat()
        ids = self.serveur.creer_transferts(
            e,
            [
                {"famille": "pc", "cle": "pc8", "source": "staging", "cible": "dev"},
                {"famille": "pc", "cle": "pc8", "source": "staging", "cible": "local"},
            ],
        )
        self.assertEqual(len(ids), 2)
        self.assertEqual([c["mode"] for c in e.creees], ["reel", "reel"])

    def test_lot_porte_la_source_et_l_empreinte_cible(self):
        lot = self.executeur.construire_lot(
            self.releves,
            "T-1",
            "staging",
            "dev",
            [{"famille": "pc", "cle": "pc8"}],
            "simulation",
            "ops-test",
        )
        op = lot["operations"][0]
        self.assertEqual((op["sha_source"], op["sha_cible_attendu"]), ("A", "B"))
        self.assertEqual(op["champs"]["texte_court"], "x")
        prog = self.executeur.programme(lot)
        self.assertNotIn('if __name__ == "__main__":\n    main()', prog)
        self.assertIn("LOT = json.loads(", prog)
        compile(prog, "programme", "exec")


class JournalTest(unittest.TestCase):
    def test_changement_detecte_entre_deux_releves(self):
        import serveur

        class FauxResumeur:
            demandes = []

            def demander(self, *a):
                self.demandes.append(a)

        e = serveur.Etat.__new__(serveur.Etat)
        e.resumeur = FauxResumeur()
        ancien = {
            "familles": {
                "pc": {"objets": {"pc8": {"sha": "A", "texte": "t1", "libelle": ""}}}
            },
            "contenus": {"t1": "a"},
        }
        nouveau = {
            "releve_le": "2026-10-15T08:00:00+00:00",
            "familles": {
                "pc": {
                    "objets": {
                        "pc8": {"sha": "B", "texte": "t2", "libelle": "", "dates": []}
                    }
                }
            },
            "contenus": {"t2": "b"},
        }
        (ev,) = e._changements("staging", ancien, nouveau, "T-0001")
        self.assertEqual(
            (ev["type"], ev["cle"], ev["tache"]), ("modifié", "pc8", "T-0001")
        )
        self.assertEqual(ev["resume"], render.cle_resume("contenu", "t1", "t2"))
        self.assertEqual(len(e.resumeur.demandes), 1)


class DateAuteurTest(unittest.TestCase):
    def test_une_copie_ne_rajeunit_pas(self):
        # Cas pc4 du 15/10 : copie staging -> local, le contenu date du 14/10.
        traces = [
            {"date": "2026-10-15T06:48:50+00:00", "source": "journal admin", "par": "ops-test",
             "copie": {"tache": "T-0004", "source": "staging", "version": "71d18e2c",
                       "date_origine": "2026-10-14T12:41:30+00:00"}},
        ]  # fmt: skip
        date, trace, copie = render.date_auteur(traces)
        self.assertEqual(date, "2026-10-14T12:41:30+00:00")
        self.assertEqual(copie["copie"]["source"], "staging")

    def test_updated_at_de_la_copie_ignore_mais_edition_posterieure_retenue(self):
        copie = {
            "date": "2026-10-15T06:48:50+00:00",
            "copie": {"source": "staging", "date_origine": None},
        }
        maj_copie = {"date": "2026-10-15T06:48:51+00:00", "source": "updated_at"}
        self.assertEqual(render.date_auteur([copie, maj_copie])[0], None)
        edition = {"date": "2026-10-15T09:00:00+00:00", "source": "journal admin"}
        self.assertEqual(
            render.date_auteur([copie, maj_copie, edition])[0], edition["date"]
        )

    def test_ordre_pc4_dev_devant_staging(self):
        cellules = {
            "local": cel("emma", None),  # copie : date d'écriture = celle de staging
            "dev": cel("restauration", "2026-10-14T13:39:27+00:00"),
            "staging": cel("emma", "2026-10-14T12:41:30+00:00"),
        }
        render.lettres(cellules)
        self.assertEqual(cellules["dev"]["version"], "A")
        self.assertEqual(cellules["staging"]["version"], "B")
        self.assertEqual(cellules["local"]["version"], "B")


class CopieJournalTest(unittest.TestCase):
    def test_message_de_copie_reconnu(self):
        import collect_snapshot

        c = collect_snapshot.lire_copie(
            "Transfert nitrates-ops T-0007 depuis staging (version 71d18e2c, écrite le 2026-10-14T12:41:30+00:00)"
        )
        self.assertEqual(
            (c["tache"], c["source"], c["date_origine"]),
            ("T-0007", "staging", "2026-10-14T12:41:30+00:00"),
        )
        ancien = collect_snapshot.lire_copie(
            "Transfert nitrates-ops T-0004 depuis staging (version 71d18e2c)"
        )
        self.assertIsNone(ancien["date_origine"])
        self.assertIsNone(collect_snapshot.lire_copie("Texte court, Blocs"))


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        import tempfile

        import executeur
        import serveur

        self.executeur, self.serveur = executeur, serveur
        self.dossier = Path(tempfile.mkdtemp())
        textes = {"tA": json.dumps({"identifiant": "pc8", "blocs": ["avant"]})}
        objets = {
            "pc8": {
                "sha": "A",
                "facettes": {"blocs": "f"},
                "texte": "tA",
                "dates": [],
                "libelle": "",
            }
        }
        self.releves = {
            "staging": {"familles": {"pc": {"objets": objets}}, "contenus": textes}
        }

    def etat(self):
        class FauxResumeur:
            version = 0

            def etat(self):
                return {}

        return self.serveur.Etat(
            ["local", "dev", "staging", "prod"],
            {"staging": {}},
            {"staging": "reel"},
            self.releves,
            None,
            None,
            self.dossier,
            FauxResumeur(),
            "conteneur",
            "ops-test",
            self.dossier / "archive",
        )

    def test_etat_avant_et_lot_de_restauration(self):
        ops = [{"famille": "pc", "cle": "pc8"}, {"famille": "pc", "cle": "pc99"}]
        avant = self.executeur.etat_avant(self.releves, "staging", ops)
        self.assertEqual(avant[0]["etat"]["champs"]["blocs"], ["avant"])
        self.assertIsNone(avant[1]["etat"])  # n'existait pas : pas de suppression
        lot = self.executeur.lot_restauration(
            avant, self.releves, "T-0200", "staging", "reel", "ops-test"
        )
        (op,) = lot["operations"]
        self.assertEqual(
            (op["sha_source"], op["sha_cible_attendu"], lot["source"]),
            ("A", "A", "archive"),
        )

    def test_archive_relue_et_tache_interrompue(self):
        e = self.etat()
        t = e.nouvelle_tache(
            "transfert", "pc8 : dev → staging", cible="staging", source="dev"
        )
        with e.verrou:
            t["statut"] = "en_cours"
        e.archiver(t, "debut")
        e2 = self.etat()  # redémarrage du serveur
        self.assertEqual(e2.taches[t["id"]]["statut"], "interrompue")
        self.assertGreaterEqual(e2.compteur, int(t["id"].split("-")[1]))
        lignes = (self.dossier / "archive" / "actions.jsonl").read_text().splitlines()
        self.assertEqual(
            [json.loads(x)["evenement"] for x in lignes], ["creation", "debut"]
        )

    def test_restauration_refusee_sans_etat_avant(self):
        e = self.etat()
        t = e.nouvelle_tache(
            "transfert",
            "pc8",
            cible="staging",
            source="dev",
            operations=[{"famille": "pc", "cle": "pc8"}],
        )
        with self.assertRaisesRegex(ValueError, "pas d'état d'avant"):
            self.serveur.creer_restauration(e, t["id"])
        with e.verrou:
            t["avant_archive"] = True
        r = self.serveur.creer_restauration(e, t["id"])
        self.assertEqual(
            (r["type"], r["restaure"], r["source"]),
            ("restauration", t["id"], "archive"),
        )
