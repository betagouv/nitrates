#!/usr/bin/env python3
"""Sonde TLS de la prod : chaque IP d'entrée Scalingo doit présenter le
certificat de nitrates.beta.gouv.fr.

Incident de novembre 2026 : des testeurs ont reçu NET::ERR_CERT_COMMON_NAME_INVALID,
un frontal Scalingo présentant le certificat générique *.osc-secnum-fr1.scalingo.io
au lieu du nôtre. La supervision updown.io n'a rien vu : elle ne teste qu'une
connexion toutes les 5 minutes, vers une seule des IP du pool. Cette sonde ouvre
plusieurs connexions vers CHAQUE IP, pour chaque nom, et vérifie le certificat
comme un navigateur (chaîne, nom, date).

Elle vérifie aussi que les enregistrements A de la zone (posés à la main le
05/08/2026) correspondent toujours au pool d'entrée annoncé par Scalingo : une
recomposition du pool sans mise à jour de la zone donne exactement le même
symptôme.

Sortie 0 si tout va bien, 1 sinon ; un message par anomalie sur stdout.
Paramètres par variables d'environnement (valeurs par défaut = prod).
"""

import os
import socket
import ssl
import sys
from datetime import datetime, timezone

DOMAINES = os.environ.get(
    "SONDE_DOMAINES", "nitrates.beta.gouv.fr www.nitrates.beta.gouv.fr"
).split()
ZONE = os.environ.get("SONDE_ZONE", "nitrates.beta.gouv.fr")
POOL = os.environ.get(
    "SONDE_POOL", "lb-pool-main.shard-0.osc-secnum-fr1.scalingo-network.com"
)
ESSAIS = int(os.environ.get("SONDE_ESSAIS", "6"))
# Scalingo renouvelle tous les 30 jours des certificats de 90 jours : il reste
# donc toujours au moins 60 jours. Sous 40, le renouvellement est en panne.
JOURS_MIN = int(os.environ.get("SONDE_JOURS_MIN", "40"))


def ipv4(nom):
    try:
        return sorted({a[4][0] for a in socket.getaddrinfo(nom, 443, socket.AF_INET)})
    except socket.gaierror:
        return []


def sonder(ip, domaine, contexte):
    """Une connexion TLS vers `ip` en annonçant `domaine` (SNI).

    Renvoie (None, jours_restants) si le certificat est valide pour le nom,
    sinon (message, None)."""
    try:
        with socket.create_connection((ip, 443), timeout=10) as brut:
            with contexte.wrap_socket(brut, server_hostname=domaine) as tls:
                cert = tls.getpeercert()
    except ssl.SSLCertVerificationError as e:
        return f"certificat refusé ({e.verify_message})", None
    except (OSError, ssl.SSLError) as e:
        return f"connexion impossible ({e.__class__.__name__}: {e})", None
    fin = datetime.fromtimestamp(ssl.cert_time_to_seconds(cert["notAfter"]), timezone.utc)
    return None, (fin - datetime.now(timezone.utc)).days


def main():
    anomalies = []
    ips_zone = ipv4(ZONE)
    ips_pool = ipv4(POOL)
    if not ips_zone:
        anomalies.append(f"DNS : aucune adresse IPv4 pour {ZONE}")
    if ips_pool and ips_zone and ips_zone != ips_pool:
        anomalies.append(
            f"DNS : les A de {ZONE} ({' '.join(ips_zone)}) ne correspondent plus "
            f"au pool d'entrée Scalingo {POOL} ({' '.join(ips_pool)})"
        )

    contexte = ssl.create_default_context()
    contexte.minimum_version = ssl.TLSVersion.TLSv1_2
    jours = []
    for ip in sorted(set(ips_zone) | set(ips_pool)):
        for domaine in DOMAINES:
            echecs = {}
            for _ in range(ESSAIS):
                erreur, restant = sonder(ip, domaine, contexte)
                if erreur:
                    echecs[erreur] = echecs.get(erreur, 0) + 1
                else:
                    jours.append(restant)
            for erreur, n in echecs.items():
                anomalies.append(f"{domaine} via {ip} : {n}/{ESSAIS} {erreur}")

    if jours and min(jours) < JOURS_MIN:
        anomalies.append(
            f"certificat : plus que {min(jours)} jours de validité "
            f"(Scalingo renouvelle normalement à 60 jours) : renouvellement en panne ?"
        )

    if anomalies:
        print("\n".join(anomalies))
        return 1
    print(
        f"OK : {len(jours)} connexions, {len(set(ips_zone) | set(ips_pool))} IP, "
        f"certificat valable encore {min(jours) if jours else '?'} jours"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
