#!/usr/bin/env bash
# REVERT_AT_MERGE_TIME_FOR_UPSTREAM_ENVERGO
# Migration de la base Docker LOCALE de PostgreSQL 13 vers 17 (Django 5.2, refs #647).
#
# A lancer une fois, depuis la racine du dépôt, quand le conteneur
# envergo_postgres (PostgreSQL 13) tourne encore. Non destructif : l'ancien
# volume envergo_postgres_data reste intact, les données sont copiées dans le
# nouveau volume envergo_postgres17_data.
#
# Les écritures faites entre le dump et la fin du script sont perdues : couper
# les conteneurs qui écrivent avant de lancer.
#
# Retour arrière : revenir aux anciens Dockerfile et docker-compose.yml, puis
# `docker compose up -d --build postgres` (l'ancien volume est réutilisé).
set -euo pipefail

CONTAINER=envergo_postgres
DUMP="$(mktemp -d)/pg13_dumpall.sql"

version=$(docker exec "$CONTAINER" psql -U envergo -d postgres -tAc "show server_version_num")
if [ "${version:0:2}" != "13" ]; then
  echo "Le conteneur $CONTAINER n'est pas en PostgreSQL 13 (server_version_num=$version), rien à faire." >&2
  exit 1
fi

echo ">>> Dump de toutes les bases PostgreSQL 13 vers $DUMP"
docker exec "$CONTAINER" pg_dumpall -U envergo > "$DUMP"
echo ">>> Taille du dump : $(du -h "$DUMP" | cut -f1)"

echo ">>> Construction de l'image PostgreSQL 17"
docker compose build postgres

echo ">>> Arrêt de l'ancien conteneur (son volume est conservé)"
docker stop "$CONTAINER" >/dev/null
docker rm "$CONTAINER" >/dev/null

echo ">>> Démarrage de PostgreSQL 17 sur le nouveau volume"
docker compose up -d postgres
for _ in $(seq 1 60); do
  docker exec "$CONTAINER" pg_isready -U envergo >/dev/null 2>&1 && break
  sleep 2
done

echo ">>> Restauration"
docker exec -i "$CONTAINER" psql -U envergo -d postgres -q -v ON_ERROR_STOP=0 < "$DUMP" > /dev/null 2> "${DUMP%.sql}.restore.log" || true
echo ">>> Erreurs de restauration (le rôle envergo existe déjà, c'est attendu) :"
grep -c "ERROR" "${DUMP%.sql}.restore.log" || true

echo ">>> Vérification"
docker exec "$CONTAINER" psql -U envergo -d postgres -tAc "select version()"
docker exec "$CONTAINER" psql -U envergo -d postgres -tAc \
  "select datname, pg_size_pretty(pg_database_size(datname)) from pg_database where not datistemplate order by 1"
echo ">>> Terminé. Dump conservé dans $DUMP"
