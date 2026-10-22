"""Applique un lot de transferts dans la base de l'environnement où il tourne.

Exécuté par `python manage.py shell -c "exec(open(...).read())"` DANS
l'environnement cible (conteneur local, ou one-off Scalingo) : on passe donc
par le code et l'ORM de la cible (cycle de vie des arbres, signaux
d'invalidation de cache, journal de l'admin), jamais par du SQL envoyé depuis
le poste.

Ce fichier n'est pas autonome : l'orchestrateur le concatène derrière
collect_snapshot.py (empreintes calculées exactement comme le relevé) et
devant une ligne qui définit LOT.

Garanties :
- tout ou rien : une seule transaction pour tout le lot ;
- concurrence : chaque opération porte l'empreinte de la cible vue par
  l'opérateur, on refuse si la cible a bougé depuis ;
- vérification : après écriture, on relit la cible avec le code du relevé et
  on compare à l'empreinte de la source ;
- simulation : même chemin complet, puis annulation de la transaction.
"""

# flake8: noqa: F821 - Releve, REFERENTIELS, sha_obj, cle_arbre et LOT viennent
# du préambule ajouté par l'orchestrateur.

import json as _json

from django.apps import apps as _apps
from django.db import connection as _connection
from django.db import transaction as _transaction

MARQUE_DEBUT = "@@RESULTAT_OPS@@"
MARQUE_FIN = "@@FIN_RESULTAT_OPS@@"

FAMILLES_MODELES = {
    "pc": ("nitrates", "CodePrescription"),
    "contenu": ("nitrates", "ContenuRichDSFR"),
    "culture": ("nitrates", "Culture"),
    "brancheculturale": ("nitrates", "BrancheCulturale"),
    "groupecultureui": ("nitrates", "GroupeCultureUI"),
    "fertilisant": ("nitrates", "Fertilisant"),
    "notereglementaire": ("nitrates", "NoteReglementaire"),
    "evenementphenologique": ("nitrates", "EvenementPhenologique"),
    "lienreference": ("nitrates", "LienReference"),
    "ouverture": ("nitrates", "DepartementOuverture"),
    "couleurzone": ("nitrates", "CouleurZone"),
}


class _Simulation(Exception):
    pass


class _Refus(Exception):
    pass


def _log(msg):
    print(f"  {msg}", flush=True)


def _objet_par_cle_naturelle(modele, valeur):
    if modele._meta.label_lower == "geodata.map":
        from django.db.models import Q

        nom, _, version = str(valeur).rpartition("@")
        qs = modele.objects.filter(name=nom)
        if version in ("", "-"):
            qs = qs.filter(Q(version="") | Q(version__isnull=True))
        else:
            qs = qs.filter(version=version)
        return qs.get()
    noms = {f.name for f in modele._meta.concrete_fields}
    for champ in ("identifiant", "cle", "code"):
        if champ in noms:
            return modele.objects.get(**{champ: valeur})
    raise _Refus(f"pas de clé naturelle connue pour {modele._meta.label}")


def _auteur():
    """Premier compte trouvé parmi les candidats (nom exact ou début d'e-mail).

    Les comptes diffèrent selon les bases (pseudo sur les envs Scalingo,
    l'e-mail beta.gouv en local) : LOT["auteur"] en liste plusieurs.
    """
    User = _apps.get_model("users", "User")
    for nom in [n.strip() for n in (LOT.get("auteur") or "").split(",") if n.strip()]:
        u = (
            User.objects.filter(name=nom).first()
            or User.objects.filter(email__istartswith=nom).first()
        )
        if u:
            return u
    return None


def _journaliser(obj, creation, message, auteur):
    if auteur is None:
        return
    from django.contrib.admin.models import ADDITION, CHANGE, LogEntry
    from django.contrib.contenttypes.models import ContentType

    LogEntry.objects.log_action(
        user_id=auteur.pk,
        content_type_id=ContentType.objects.get_for_model(obj).pk,
        object_id=obj.pk,
        object_repr=str(obj)[:200],
        action_flag=ADDITION if creation else CHANGE,
        change_message=message,
    )


def _contexte_historique(message, auteur):
    import contextlib

    try:
        from envergo.nitrates.historique import contexte_revision
    except ImportError:  # env sans historique des contenus
        return contextlib.nullcontext()
    return contexte_revision(
        origine="commande", motif=message, source="nitrates-ops", auteur=auteur
    )


def _spec(famille):
    return next(s for s in REFERENTIELS if s["famille"] == famille)


def _etat_referentiel(releve, famille, cle):
    objets = releve.referentiel(_spec(famille))["objets"]
    o = objets.get(cle)
    return o and o["sha"], o


def _etat_arbre(releve, cle):
    actifs = [
        v
        for v in releve.arbres()["versions"]
        if v["cle"] == cle and v["statut"] == "active"
    ]
    return (actifs[0]["sha"] if actifs else None), (actifs[0] if actifs else None)


def _appliquer_referentiel(op, auteur, message):
    modele = _apps.get_model(*FAMILLES_MODELES[op["famille"]])
    champs = op["champs"]
    cles = _spec(op["famille"])["cle"]
    lookup = {c: champs[c] for c in cles}
    obj = modele.objects.filter(**lookup).first()
    creation = obj is None
    if creation:
        obj = modele(**lookup)
    m2m = {}
    ignores = []
    for nom, valeur in champs.items():
        try:
            champ = modele._meta.get_field(nom)
        except Exception:  # noqa: BLE001 - champ absent du schéma cible
            ignores.append(nom)
            continue
        if champ.primary_key or nom in cles:
            continue
        if champ.many_to_many:
            m2m[nom] = valeur
        elif champ.is_relation:
            setattr(
                obj,
                nom,
                (
                    None
                    if valeur is None
                    else _objet_par_cle_naturelle(champ.related_model, valeur)
                ),
            )
        else:
            setattr(obj, champ.attname, valeur)
    obj.save()
    for nom, valeurs in m2m.items():
        cible = modele._meta.get_field(nom).related_model
        getattr(obj, nom).set([_objet_par_cle_naturelle(cible, v) for v in valeurs])
    if ignores:
        _log(f"champs absents du schéma cible, ignorés : {', '.join(ignores)}")
    absents = [
        f.name
        for f in modele._meta.concrete_fields
        if not f.primary_key
        and f.name not in champs
        and f.attname not in champs
        and f.name not in VOLATILS
    ]
    if absents:
        _log(
            f"champs de la cible absents du lot, laissés tels quels : {', '.join(absents)}"
        )
    _journaliser(obj, creation, message, auteur)
    return "création" if creation else "mise à jour"


def _valider_arbre(op, cfg):
    """Valide l'arbre avec le code et les référentiels de CETTE base (version
    de l'application, PC présentes) avant de l'activer. Un arbre venu d'un env
    plus récent peut s'appuyer sur du code ou des PC que la cible n'a pas."""
    try:
        from envergo.nitrates.yaml_tree.loader import load_referentiels
        from envergo.nitrates.yaml_tree.validator import ValidationError, validate_arbre
    except ImportError:
        _log("validateur d'arbre absent de cette version : arbre non validé")
        return
    try:
        validate_arbre(op["contenu"], load_referentiels(), scope=cfg["scope"])
    except ValidationError as e:
        raise _Refus(
            f"{op['cle']} : arbre invalide pour le code de cette base : {'; '.join(e.errors)[:500]}"
        )
    _log("arbre validé par le code de la cible")


def _appliquer_arbre(op, auteur, message):
    DecisionTree = _apps.get_model("nitrates", "DecisionTree")
    Map = _apps.get_model("geodata", "Map")
    cfg = op["config"]
    carte = (
        _objet_par_cle_naturelle(Map, cfg["activation_map"])
        if cfg.get("activation_map")
        else None
    )
    actif = DecisionTree.objects.filter(
        status="active",
        scope=cfg["scope"],
        region_code=cfg["region_code"],
        activation_map=carte,
    ).first()
    arbre = DecisionTree(
        name=f"{op['nom_source']} (transfert {LOT['ref']} depuis {LOT['source']})",
        status="draft",
        scope=cfg["scope"],
        region_code=cfg["region_code"],
        weight=cfg["weight"],
        activation_map=carte,
        contenu=op["contenu"],
        contenu_yaml_brut=op.get("yaml") or "",
        parent=actif,
        created_by=auteur,
    )
    _valider_arbre(op, cfg)
    arbre.save()
    arbre.activate()
    _log(
        f"arbre #{arbre.pk} créé et activé"
        + (f", #{actif.pk} archivé" if actif else "")
    )
    _journaliser(arbre, True, message, auteur)
    return "nouvelle version active"


def _arbres_citant(identifiant):
    """Arbres actifs dont la logique cite cet identifiant (ex. "pc17")."""
    DecisionTree = _apps.get_model("nitrates", "DecisionTree")
    jeton = _json.dumps(identifiant, ensure_ascii=False)
    return [
        t.name
        for t in DecisionTree.objects.filter(status="active")
        if jeton in _json.dumps(t.contenu, ensure_ascii=False)
    ]


def _journaliser_suppression(obj, message, auteur):
    if auteur is None:
        return
    from django.contrib.admin.models import DELETION, LogEntry
    from django.contrib.contenttypes.models import ContentType

    LogEntry.objects.log_action(
        user_id=auteur.pk,
        content_type_id=ContentType.objects.get_for_model(obj).pk,
        object_id=obj.pk,
        object_repr=str(obj)[:200],
        action_flag=DELETION,
        change_message=message,
    )


def _supprimer_referentiel(op, auteur, message):
    from django.contrib.admin.utils import NestedObjects

    modele = _apps.get_model(*FAMILLES_MODELES[op["famille"]])
    cles = _spec(op["famille"])["cle"]
    obj = modele.objects.get(**dict(zip(cles, op["cle"].split("/", len(cles) - 1))))
    if op["famille"] == "pc":
        citants = _arbres_citant(obj.identifiant)
        if citants:
            raise _Refus(
                f"{op['cle']} est encore cité par l'arbre actif {', '.join(citants)} : le retirer de l'arbre d'abord"
            )
    # Ce que la suppression emporterait ou modifierait, calculé comme la page de
    # confirmation de suppression de l'admin Django.
    collecteur = NestedObjects(using=obj._state.db)
    collecteur.collect([obj])
    if collecteur.protected:
        noms = ", ".join(str(o) for o in list(collecteur.protected)[:5])
        raise _Refus(f"{op['cle']} : suppression bloquée, encore utilisé par {noms}")
    emportes = []
    for m, objets in collecteur.data.items():
        for o in objets:
            if o == obj:
                continue
            # La composition propre d'une PC fusionnée (lignes de la table de liaison
            # dont elle est la source) part avec elle : ce n'est pas un effet de bord.
            if m._meta.auto_created and any(
                f.related_model is modele
                and f.name.startswith("from_")
                and getattr(o, f.attname) == obj.pk
                for f in m._meta.concrete_fields
            ):
                continue
            emportes.append(f"{m._meta.verbose_name} « {o} »")
    for (champ, _valeur), objets in getattr(collecteur, "field_updates", {}).items():
        for o in _aplatir(objets):
            emportes.append(
                f"{champ.model._meta.verbose_name} « {o} » ({champ.name} remis à vide)"
            )
    if emportes:
        raise _Refus(
            f"{op['cle']} : la suppression emporterait ou modifierait aussi {', '.join(emportes[:6])}"
            + (f" (+{len(emportes) - 6})" if len(emportes) > 6 else "")
            + " : à traiter d'abord"
        )
    generique = getattr(obj, "variante_de", None)
    if generique is not None:
        _log(
            f"attention : {op['cle']} est une variante de {generique.identifiant} ; après suppression, "
            f"c'est {generique.identifiant} qui s'appliquera dans sa zone"
        )
    _journaliser_suppression(obj, message, auteur)
    obj.delete()
    return "supprimé"


def _aplatir(objets):
    """field_updates contient selon la version de Django des objets ou des QuerySet."""
    for x in objets if isinstance(objets, (list, tuple, set)) else [objets]:
        if hasattr(x, "model") and hasattr(x, "iterator"):
            yield from x
        else:
            yield x


def _supprimer_arbre(op, auteur, message):
    """Un arbre n'est jamais effacé : l'actif de cette zone passe en archive."""
    from django.utils import timezone

    DecisionTree = _apps.get_model("nitrates", "DecisionTree")
    maintenant = timezone.now()
    actifs = [
        t
        for t in DecisionTree.objects.filter(status="active").select_related(
            "activation_map"
        )
        if cle_arbre(
            t.scope, t.region_code, t.activation_map.name if t.activation_map else None
        )
        == op["cle"]
    ]
    for t in actifs:
        t.status = "archive"
        t.name = f"{t.name} – archive {maintenant:%Y-%m-%d %H:%M}"
        t.save(update_fields=["status", "name", "updated_at"])
        _journaliser(t, False, message, auteur)
        _log(f"arbre #{t.pk} archivé")
    return "arbre actif archivé"


def _executer():
    releve = Releve(_connection)
    auteur = _auteur()
    if LOT.get("auteur") and auteur is None:
        _log(
            f"auteur « {LOT['auteur']} » introuvable dans cette base : pas d'entrée au journal admin"
        )
    resultats = []
    simulation = LOT["mode"] != "reel"
    print(
        f"Lot {LOT['ref']} : {len(LOT['operations'])} opération(s), {LOT['source'] or 'suppression'} → cette base, "
        f"{'SIMULATION (annulée à la fin)' if simulation else 'écriture réelle'}",
        flush=True,
    )
    try:
        with _transaction.atomic():
            for op in LOT["operations"]:
                print(f"- {op['famille']} {op['cle']}", flush=True)
                arbre = op["famille"] == "arbre"
                avant, _ = (
                    _etat_arbre(releve, op["cle"])
                    if arbre
                    else _etat_referentiel(releve, op["famille"], op["cle"])
                )
                if op.get("action") == "supprimer":
                    if avant is None:
                        _log("déjà absent de la cible, rien à faire")
                        resultats.append(
                            {
                                "cle": op["cle"],
                                "famille": op["famille"],
                                "action": "déjà absent",
                                "verifie": True,
                            }
                        )
                        continue
                    if avant != op.get("sha_cible_attendu"):
                        raise _Refus(
                            f"{op['cle']} : la cible a changé depuis l'affichage. Rafraîchir et recommencer."
                        )
                    message = f"Suppression nitrates-ops {LOT['ref']}" + (
                        f" : absent de {LOT['source']}" if LOT.get("source") else ""
                    )
                    with _contexte_historique(message, auteur):
                        action = (
                            _supprimer_arbre(op, auteur, message)
                            if arbre
                            else _supprimer_referentiel(op, auteur, message)
                        )
                    apres, _ = (
                        _etat_arbre(releve, op["cle"])
                        if arbre
                        else _etat_referentiel(releve, op["famille"], op["cle"])
                    )
                    verifie = apres is None
                    _log(
                        f"{action} ; vérification : {'absent de la cible' if verifie else 'ENCORE PRÉSENT'}"
                    )
                    resultats.append(
                        {
                            "cle": op["cle"],
                            "famille": op["famille"],
                            "action": action,
                            "verifie": verifie,
                            "ecarts": [],
                        }
                    )
                    continue
                if avant != op.get("sha_cible_attendu"):
                    raise _Refus(
                        f"{op['cle']} : la cible a changé depuis l'affichage "
                        f"(attendu {str(op.get('sha_cible_attendu'))[:8]}, trouvé {str(avant)[:8]}). Rafraîchir et recommencer."
                    )
                if avant == op["sha_source"]:
                    _log("déjà identique à la source, rien à faire")
                    resultats.append(
                        {
                            "cle": op["cle"],
                            "famille": op["famille"],
                            "action": "identique",
                            "verifie": True,
                        }
                    )
                    continue
                message = (
                    f"Transfert nitrates-ops {LOT['ref']} depuis {LOT['source']} "
                    f"(version {op['sha_source'][:8]}, écrite le {op.get('date_origine') or 'date inconnue'})"
                )
                # L'historique des contenus (0.6.4+) note le motif de la copie :
                # le relevé la reconnaît et ne rajeunit pas le contenu.
                with _contexte_historique(message, auteur):
                    action = (
                        _appliquer_arbre(op, auteur, message)
                        if arbre
                        else _appliquer_referentiel(op, auteur, message)
                    )
                apres, detail = (
                    _etat_arbre(releve, op["cle"])
                    if arbre
                    else _etat_referentiel(releve, op["famille"], op["cle"])
                )
                verifie = apres == op["sha_source"]
                ecarts = []
                if not verifie and detail and op.get("facettes_source"):
                    ecarts = [
                        k
                        for k, v in detail["facettes"].items()
                        if op["facettes_source"].get(k) != v
                    ]
                _log(
                    f"{action} ; vérification : {'identique à la source' if verifie else 'ÉCART ' + ', '.join(ecarts)}"
                )
                resultats.append(
                    {
                        "cle": op["cle"],
                        "famille": op["famille"],
                        "action": action,
                        "verifie": verifie,
                        "ecarts": ecarts,
                    }
                )
            if not all(r["verifie"] for r in resultats):
                raise _Refus(
                    "au moins une opération ne correspond pas à la source après écriture : tout est annulé"
                )
            if simulation:
                raise _Simulation()
        statut = "applique"
    except _Simulation:
        statut = "simule"
        print("Simulation : tout s'est bien passé, transaction annulée.", flush=True)
    except _Refus as e:
        statut = "refuse"
        print(f"REFUS : {e}", flush=True)
    except Exception as e:  # noqa: BLE001 - on rapporte tout à l'orchestrateur
        statut = "erreur"
        print(f"ERREUR : {e!r}", flush=True)
        import traceback

        traceback.print_exc()
    print(MARQUE_DEBUT)
    print(_json.dumps({"statut": statut, "operations": resultats}, ensure_ascii=False))
    print(MARQUE_FIN, flush=True)


_executer()
