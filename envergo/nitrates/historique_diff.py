"""Différences entre versions d'un contenu riche, et annulation ligne à ligne.

Un contenu (liste de blocs DSFR) est mis à plat en « unités », une par ligne
affichée : un bloc simple, un item de liste (avec sa profondeur), l'ouverture
d'un volet ; plus des marqueurs invisibles (début / fin de liste, fin de
volet). La mise à plat est réversible : `reconstruire(lineariser(b)) == b`.

La différence entre deux versions se calcule sur ces unités. Annuler une
ligne d'un changement applique le patch inverse à la version ACTUELLE, qui a
pu évoluer depuis : on situe chaque unité du changement dans la version
actuelle ; si elle n'y est plus telle quelle, c'est un conflit et la ligne
n'est pas annulable.
"""

import copy
import difflib
import json
import os

# Un retrait et un ajout voisins sont présentés comme une seule ligne modifiée
# s'ils sont très proches, ou assez proches ET gardent le début ou la fin de la
# phrase (une reformulation). Sinon, deux phrases différentes qui partagent un
# fragment (« 70 kg d'azote … par hectare ») resteraient appariées à tort.
SIMILARITE_FORTE = 0.85
SIMILARITE_MODIF = 0.4
BORD_COMMUN = 12
# Marqueurs de fermeture : jamais affichés ni appariés en modification.
MARQUEURS = ("/liste", "/volet")


def _texte(valeur):
    if isinstance(valeur, list):
        return "".join(
            s if isinstance(s, str) else (s or {}).get("texte", "") for s in valeur
        )
    return valeur or ""


def _blocs(contenu):
    if isinstance(contenu, dict):
        return contenu.get("blocs") or []
    return contenu or []


def _unite(genre, data, profondeur=0, niveau=0):
    return {"k": genre, "d": profondeur, "n": niveau, "data": data}


def lineariser(contenu, niveau=0):
    """Blocs DSFR -> liste plate d'unités (niveau = imbrication dans les volets)."""
    unites = []

    def items(liste, profondeur):
        for it in liste or []:
            it = it if isinstance(it, dict) else {"texte": it}
            unites.append(
                _unite(
                    "item",
                    {k: v for k, v in it.items() if k != "enfants"},
                    profondeur,
                    niveau,
                )
            )
            items(it.get("enfants"), profondeur + 1)

    for bloc in _blocs(contenu):
        if not isinstance(bloc, dict):
            continue
        t = bloc.get("type")
        data = bloc.get("data") or {}
        if t == "liste":
            meta = {k: v for k, v in data.items() if k != "items"}
            unites.append(_unite("liste", meta, 0, niveau))
            items(data.get("items"), 0)
            unites.append(_unite("/liste", {}, 0, niveau))
        elif t == "foldable":
            meta = {k: v for k, v in data.items() if k != "blocs"}
            unites.append(_unite("volet", meta, 0, niveau))
            unites += lineariser(data.get("blocs"), niveau + 1)
            unites.append(_unite("/volet", {}, 0, niveau))
        else:
            unites.append(_unite("bloc", copy.deepcopy(bloc), 0, niveau))
    return unites


def reconstruire(unites):
    """Liste d'unités -> blocs DSFR (inverse de `lineariser`, tolérant :
    un item hors liste ouvre une liste, une liste vide disparaît)."""
    racine = []
    conteneurs = [racine]
    liste = None
    chemin = []  # derniers items par profondeur dans la liste courante

    def fermer_liste():
        nonlocal liste, chemin
        liste, chemin = None, []

    for u in unites:
        k = u["k"]
        if k == "liste":
            liste = {"type": "liste", "data": {**copy.deepcopy(u["data"]), "items": []}}
            conteneurs[-1].append(liste)
            chemin = []
        elif k == "/liste":
            fermer_liste()
        elif k == "item":
            if liste is None:
                liste = {"type": "liste", "data": {"items": []}}
                conteneurs[-1].append(liste)
                chemin = []
            item = copy.deepcopy(u["data"])
            d = min(u["d"], len(chemin))
            if d == 0:
                liste["data"]["items"].append(item)
            else:
                chemin[d - 1].setdefault("enfants", []).append(item)
            chemin = chemin[:d] + [item]
        elif k == "volet":
            fermer_liste()
            volet = {
                "type": "foldable",
                "data": {**copy.deepcopy(u["data"]), "blocs": []},
            }
            conteneurs[-1].append(volet)
            conteneurs.append(volet["data"]["blocs"])
        elif k == "/volet":
            fermer_liste()
            if len(conteneurs) > 1:
                conteneurs.pop()
        else:
            fermer_liste()
            conteneurs[-1].append(copy.deepcopy(u["data"]))

    def nettoyer(blocs):
        out = []
        for b in blocs:
            if b.get("type") == "liste" and not b["data"].get("items"):
                continue
            if b.get("type") == "foldable":
                b["data"]["blocs"] = nettoyer(b["data"]["blocs"])
            out.append(b)
        return out

    return nettoyer(racine)


def cle(u):
    return json.dumps(
        [u["k"], u["d"], u["n"], u["data"]], sort_keys=True, ensure_ascii=False
    )


def libelle(u):
    """Ligne telle qu'affichée dans la comparaison."""
    retrait = "    " * u["n"]
    k, data = u["k"], u["data"]
    if k == "item":
        puce = "•" if u["d"] == 0 else "◦"
        return f"{retrait}{'    ' * (u['d'] + 1)}{puce} {_texte(data.get('texte'))}"
    if k == "volet":
        return f"{retrait}▸ {_texte(data.get('titre'))}"
    if k == "liste":
        style = data.get("style")
        return f"{retrait}(liste{' ' + style if style else ''})"
    if k == "/liste":
        return f"{retrait}(fin de liste)"
    if k == "/volet":
        return f"{retrait}(fin du volet)"
    t = data.get("type")
    d = data.get("data") or {}
    if t == "titre_principal":
        return f"{retrait}# {_texte(d.get('texte'))}"
    if t == "titre_paragraphe":
        return f"{retrait}## {_texte(d.get('texte'))}"
    if t in ("paragraphe", "citation"):
        return f"{retrait}{_texte(d.get('texte'))}"
    if t == "tableau":
        return "\n".join(
            f"{retrait}| " + " | ".join(_texte(c) for c in ligne) + " |"
            for ligne in d.get("lignes") or []
        )
    return f"{retrait}[{t}]"


def _texte_comparable(u):
    return libelle(u).strip()


def _texte_brut(u):
    data = u["data"]
    if u["k"] == "item":
        return _texte(data.get("texte"))
    if u["k"] == "volet":
        return _texte(data.get("titre"))
    if u["k"] == "bloc":
        return _texte((data.get("data") or {}).get("texte"))
    return ""


def _meme_phrase(a, b):
    """Deux unités de même genre : versions d'une même phrase ?"""
    ta, tb = _texte_brut(a), _texte_brut(b)
    ratio = difflib.SequenceMatcher(
        None, _texte_comparable(a), _texte_comparable(b)
    ).ratio()
    if ratio >= SIMILARITE_FORTE:
        return True
    if ratio < SIMILARITE_MODIF:
        return False
    debut = len(os.path.commonprefix([ta, tb]))
    fin = len(os.path.commonprefix([ta[::-1], tb[::-1]]))
    return max(debut, fin) >= BORD_COMMUN


def differences(base, cible):
    """Lignes de la comparaison base -> cible.

    Chaque ligne : {"genre": egal|ajout|retrait|modif, "base": i|None,
    "cible": j|None, "op": identifiant stable ou None}. Les marqueurs de liste
    invisibles inchangés ne produisent pas de ligne."""
    ub, uc = lineariser(base), lineariser(cible)
    lignes = []
    sm = difflib.SequenceMatcher(
        None, [cle(u) for u in ub], [cle(u) for u in uc], autojunk=False
    )
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for i, j in zip(range(i1, i2), range(j1, j2)):
                lignes.append({"genre": "egal", "base": i, "cible": j, "op": None})
            continue
        anciens, nouveaux = list(range(i1, i2)), list(range(j1, j2))
        # Appariement en modification : même genre, même profondeur, texte proche.
        paires, libres_n = [], list(nouveaux)
        for i in anciens:
            choisi = None
            for j in libres_n:
                if (ub[i]["k"], ub[i]["d"], ub[i]["n"]) == (
                    uc[j]["k"],
                    uc[j]["d"],
                    uc[j]["n"],
                ) and ub[i]["k"] not in MARQUEURS:
                    if ub[i]["k"] in ("volet", "liste") or _meme_phrase(ub[i], uc[j]):
                        choisi = j
                        break
            if choisi is not None:
                libres_n.remove(choisi)
            paires.append((i, choisi))
        restants = list(libres_n)
        for i, j in paires:
            if j is None:
                lignes.append(
                    {
                        "genre": "retrait",
                        "base": i,
                        "cible": None,
                        "insertion": j1,
                        "op": f"r{i}",
                    }
                )
            else:
                # Les ajouts non appariés situés avant cette modification d'abord.
                while restants and restants[0] < j:
                    jj = restants.pop(0)
                    lignes.append(
                        {"genre": "ajout", "base": None, "cible": jj, "op": f"a{jj}"}
                    )
                lignes.append(
                    {"genre": "modif", "base": i, "cible": j, "op": f"m{i}-{j}"}
                )
        for jj in restants:
            lignes.append({"genre": "ajout", "base": None, "cible": jj, "op": f"a{jj}"})
    return ub, uc, lignes


class Conflit(Exception):
    pass


def _correspondance(source, actuelle):
    """Index des unités de `source` retrouvées telles quelles dans `actuelle`."""
    sm = difflib.SequenceMatcher(
        None, [cle(u) for u in source], [cle(u) for u in actuelle], autojunk=False
    )
    corr = {}
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for i, j in zip(range(i1, i2), range(j1, j2)):
                corr[i] = j
    return corr


def _completer(ops, lignes, ub, uc):
    """Complète la sélection pour garder un contenu bien formé : annuler
    l'ouverture d'un volet (ou d'une liste) annule aussi sa fermeture et,
    pour un volet, tout ce qu'il contient ; et inversement."""
    par_op = {lg["op"]: lg for lg in lignes if lg["op"]}
    par_index = {}
    for lg in lignes:
        if lg["genre"] == "retrait":
            par_index[("b", lg["base"])] = lg["op"]
        elif lg["genre"] == "ajout":
            par_index[("c", lg["cible"])] = lg["op"]
    choisis = set(ops)
    for op in list(choisis):
        lg = par_op.get(op)
        if not lg or lg["genre"] == "modif":
            continue
        cote, seq, idx = (
            ("b", ub, lg["base"])
            if lg["genre"] == "retrait"
            else ("c", uc, lg["cible"])
        )
        k = seq[idx]["k"]
        if k not in ("volet", "liste", "/volet", "/liste"):
            continue
        pair = {
            "volet": "/volet",
            "liste": "/liste",
            "/volet": "volet",
            "/liste": "liste",
        }[k]
        pas = 1 if k in ("volet", "liste") else -1
        prof, i = 0, idx + pas
        while 0 <= i < len(seq):
            if seq[i]["k"] == k:
                prof += 1
            elif seq[i]["k"] == pair:
                if prof == 0:
                    break
                prof -= 1
            i += pas
        if not (0 <= i < len(seq)):
            continue
        debut, fin = sorted((idx, i))
        bornes = range(debut, fin + 1) if k in ("volet", "/volet") else (debut, fin)
        for x in bornes:
            o = par_index.get((cote, x))
            if o:
                choisis.add(o)
    return choisis


def _position_retrait(lg, corr):
    """Où réinsérer, dans la version actuelle, une unité retirée par le
    changement (None si son voisinage a changé depuis)."""
    ancre = lg["insertion"]
    if ancre == 0:
        return 0
    if (ancre - 1) in corr:
        return corr[ancre - 1] + 1
    if ancre in corr:
        return corr[ancre]
    return None


def _deja_presente(unite, ua, position, rayon=3):
    """L'unité retirée a-t-elle déjà été remise à cet endroit depuis ?"""
    c = cle(unite)
    debut, fin = max(0, position - rayon), position + rayon
    return any(cle(u) == c for u in ua[debut:fin])


def lignes_annulables(base, cible, actuel):
    """Pour chaque ligne changée : peut-on l'annuler sur la version actuelle ?"""
    ub, uc, lignes = differences(base, cible)
    ua = lineariser(actuel)
    corr = _correspondance(uc, ua)
    for lg in lignes:
        if lg["genre"] in ("ajout", "modif"):
            lg["annulable"] = lg["cible"] in corr
        elif lg["genre"] == "retrait":
            position = _position_retrait(lg, corr)
            lg["deja"] = position is not None and _deja_presente(
                ub[lg["base"]], ua, position
            )
            lg["annulable"] = position is not None and not lg["deja"]
        else:
            lg["annulable"] = False
    return ub, uc, lignes


def annuler(base, cible, actuel, ops):
    """Applique à `actuel` l'inverse des lignes `ops` du changement base -> cible.
    Renvoie les nouveaux blocs ; lève Conflit si une ligne n'est plus annulable."""
    ub, uc, lignes = differences(base, cible)
    ua = lineariser(actuel)
    corr = _correspondance(uc, ua)
    choisis = _completer(ops, lignes, ub, uc)
    par_op = {lg["op"]: lg for lg in lignes if lg["op"]}
    inconnus = set(choisis) - set(par_op)
    if inconnus:
        raise Conflit(f"Lignes inconnues : {', '.join(sorted(inconnus))}")
    supprimer, remplacer, inserer = set(), {}, {}
    en_conflit = []
    for op in sorted(
        choisis,
        key=lambda o: (par_op[o]["base"] if par_op[o]["base"] is not None else -1, o),
    ):
        lg = par_op[op]
        if lg["genre"] == "ajout":
            if lg["cible"] not in corr:
                en_conflit.append(libelle(uc[lg["cible"]]))
                continue
            supprimer.add(corr[lg["cible"]])
        elif lg["genre"] == "modif":
            if lg["cible"] not in corr:
                en_conflit.append(libelle(uc[lg["cible"]]))
                continue
            remplacer[corr[lg["cible"]]] = ub[lg["base"]]
        elif lg["genre"] == "retrait":
            position = _position_retrait(lg, corr)
            if position is None or _deja_presente(ub[lg["base"]], ua, position):
                en_conflit.append(libelle(ub[lg["base"]]))
                continue
            inserer.setdefault(position, []).append(ub[lg["base"]])
    if en_conflit:
        raise Conflit(
            "Ces lignes ont été modifiées depuis et ne peuvent plus être annulées : "
            + " ; ".join(f"« {x.strip()[:80]} »" for x in en_conflit)
        )
    resultat = []
    for k in range(len(ua) + 1):
        resultat += [copy.deepcopy(u) for u in inserer.get(k, [])]
        if k < len(ua) and k not in supprimer:
            resultat.append(copy.deepcopy(remplacer.get(k, ua[k])))
    blocs = reconstruire(resultat)
    if isinstance(actuel, dict):
        return {**actuel, "blocs": blocs}
    return blocs
