"""Genere les points de test preview par region x profil SIG (metropole).

Contexte : les liens du viewer YAML d'un arbre choisissent un "point de test"
(lat/lng/code_insee) via `point_par_defaut_scope`. On veut, pour chaque region
metropolitaine et chaque combinaison SIG REELLEMENT existante, un point commune
verifie, afin que la preview d'un arbre tombe dans la bonne zone quelle que soit
la region (forward compatibility demandee).

Dimensions SIG (orthogonales, cf. _SIG_RESOLVERS de preview.py et le catalog
moulinette) :
  - en_zone_vulnerable : True / False           (couche ZV, resolue par geo)
  - zone_note_5        : True / False           (NoteReglementaire, par insee)
  - zonage_montagne    : non_montagne / note_6 / note_7  (CSV, par insee)

Beaucoup de combinaisons N'EXISTENT PAS geographiquement (pas de montagne en
Hauts-de-France, note_5 limitee a R76/R93 + 24/33/40/47/64...). On ne genere que
les profils presents dans les donnees ; les cases vides sont laissees au fallback
national (documente), on n'invente aucune coordonnee.

Methode (aucune invention) :
  1. Enumeration des communes candidates depuis le CSV zone_montagne (34k communes,
     12 regions) croise avec les resolveurs reels (zone_note_5_pour_commune,
     zonage_montagne_pour_commune).
  2. Pour chaque (region, profil) on prend une commune candidate et on recupere son
     centre officiel via geo.api.gouv.fr (lat/lng reels).
  3. Verification croisee : on construit le catalog MoulinetteNitrates sur ce
     point + code_insee et on verifie que le profil obtenu correspond EXACTEMENT
     au profil vise (ZV, note_5, montagne). Sinon on essaie la commune suivante.

Sortie : un JSON {region_code: {profil: {lat,lng,code_insee,nom,...}}} ecrit sur
disque, a transformer ensuite en _POINTS / mappings dans preview.py.

Usage :
    docker compose run --rm django python -m envergo.nitrates.scripts.generate_region_points \\
        --out /app/envergo/nitrates/scripts/region_points.json [--regions 32,44] [--limit-candidates 40]
"""

import argparse
import csv
import json
import os
import time
import urllib.request
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
django.setup()

from envergo.nitrates.models import MoulinetteNitrates  # noqa: E402
from envergo.nitrates.zonage_montagne import zonage_montagne_pour_commune  # noqa: E402
from envergo.nitrates.zonage_note_5 import zone_note_5_pour_commune  # noqa: E402

CSV_PATH = (
    Path(__file__).resolve().parent.parent
    / "assets"
    / "zone_montagne_communes_2026-04-30.csv"
)

GEO_API = "https://geo.api.gouv.fr/communes/{insee}?fields=nom,centre,codeRegion,codeDepartement"


def _profil_attendu(code_insee: str, est_zv_csv: bool) -> tuple:
    """Profil SIG (zv, note_5, montagne) attendu pour une commune, calcule via les
    resolveurs REELS (pas le CSV brut, sauf pour ZV qui vient du CSV en
    pre-filtre ; la verite ZV finale sera le catalog geo)."""
    note5 = zone_note_5_pour_commune(code_insee)
    montagne = zonage_montagne_pour_commune(code_insee)  # variante elargie (defaut)
    return (est_zv_csv, note5, montagne)


def _profil_key(zv: bool, note5: bool, montagne: str) -> str:
    """Cle de profil lisible et stable pour le mapping."""
    parts = ["zv" if zv else "hors_zv"]
    if note5:
        parts.append("note5")
    if montagne != "non_montagne":
        parts.append(montagne)  # montagne_note_6 / montagne_note_7
    return "__".join(parts)


def _load_candidates(regions_filter):
    """Retourne {region_code: {profil_key: [ (insee, nom) ... ]}} depuis le CSV."""
    out = {}
    with open(CSV_PATH, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            region = r["Code région"]
            if regions_filter and region not in regions_filter:
                continue
            insee = (r["code_commune"] or "").strip()
            if not insee:
                continue
            # ZV du CSV : 'C' (concerne) ou 'PC' (partiel) -> True. '', 'NC' -> False.
            est_zv = r["est_zone_vulnerable"] in ("C", "PC")
            zv, note5, montagne = _profil_attendu(insee, est_zv)
            key = _profil_key(zv, note5, montagne)
            out.setdefault(region, {}).setdefault(key, []).append(
                (insee, r["nom_commune"])
            )
    return out


def _geocode(insee: str):
    """Centre officiel d'une commune via geo.api.gouv.fr. Retourne dict ou None."""
    url = GEO_API.format(insee=insee)
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    centre = (data or {}).get("centre") or {}
    coords = centre.get("coordinates")
    if not coords or len(coords) != 2:
        return None
    lng, lat = coords
    return {
        "lat": f"{lat:.6f}",
        "lng": f"{lng:.6f}",
        "code_insee": insee,
        "nom": data.get("nom"),
        "region_code": data.get("codeRegion"),
        "department_code": data.get("codeDepartement"),
    }


def _verifier_catalog(point, profil_attendu):
    """Construit le catalog moulinette et verifie que le profil obtenu == attendu.
    Retourne (ok, catalog_profil)."""
    zv_att, note5_att, montagne_att = profil_attendu
    m = MoulinetteNitrates(
        form_kwargs={
            "data": {
                "lat": point["lat"],
                "lng": point["lng"],
                "code_insee": point["code_insee"],
            }
        }
    )
    if not m.is_evaluated():
        m.evaluate()
    cat = m.catalog
    zv = bool(cat.get("en_zone_vulnerable"))
    note5 = bool(cat.get("zone_note_5"))
    montagne = cat.get("zone_montagne_classification") or "non_montagne"
    region = cat.get("region_code")
    obtenu = (zv, note5, montagne, region)
    ok = zv == zv_att and note5 == note5_att and montagne == montagne_att
    return ok, obtenu


def generer(regions_filter, limit_candidates, sleep):
    candidates = _load_candidates(regions_filter)
    resultat = {}
    rapport = []
    for region in sorted(candidates):
        resultat.setdefault(region, {})
        for profil_key, communes in sorted(candidates[region].items()):
            # profil attendu : recalcule depuis la 1re commune (toutes memes flags)
            insee0 = communes[0][0]
            est_zv = profil_key.startswith("zv")
            attendu = _profil_attendu(insee0, est_zv)
            trouve = None
            for insee, nom in communes[:limit_candidates]:
                point = _geocode(insee)
                if sleep:
                    time.sleep(sleep)
                if point is None:
                    continue
                ok, obtenu = _verifier_catalog(point, attendu)
                # on exige aussi que la region resolue == region cible
                if ok and obtenu[3] == region:
                    point["profil"] = profil_key
                    trouve = point
                    rapport.append(
                        f"OK   region={region} profil={profil_key:<30} "
                        f"-> {nom} ({insee}) lat={point['lat']} lng={point['lng']}"
                    )
                    break
            if trouve:
                resultat[region][profil_key] = trouve
            else:
                rapport.append(
                    f"MISS region={region} profil={profil_key:<30} "
                    f"-> aucune commune verifiee sur {len(communes[:limit_candidates])} essais"
                )
        if not resultat[region]:
            del resultat[region]
    return resultat, rapport


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument(
        "--regions",
        default="",
        help="filtre codes region INSEE separes par virgule (ex 32,44). Vide = toutes.",
    )
    p.add_argument("--limit-candidates", type=int, default=40)
    p.add_argument(
        "--sleep",
        type=float,
        default=0.1,
        help="pause entre appels API (politesse geo.api.gouv.fr)",
    )
    args = p.parse_args()
    regions_filter = {r.strip() for r in args.regions.split(",") if r.strip()}

    resultat, rapport = generer(regions_filter, args.limit_candidates, args.sleep)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(resultat, f, ensure_ascii=False, indent=2, sort_keys=True)

    print("\n".join(rapport))
    print(
        f"\n=== {sum(len(v) for v in resultat.values())} points ecrits dans {args.out} ==="
    )
    for region in sorted(resultat):
        print(f"  region {region}: {sorted(resultat[region].keys())}")


if __name__ == "__main__":
    main()
